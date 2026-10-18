#!/usr/bin/env python3
"""Watchdog superviseur indépendant pour un Pod RunPod borné.

Ce script est délibérément séparé du benchmark. Il ne dépend d'aucune
sortie du run GPU : il photographie les Pods présents avant la campagne,
exige un nom exact unique, mémorise l'ID apparu après armement et applique
l'échéance de terminaison. Tant qu'il tourne, il supprime ce Pod dès
l'échéance atteinte, même si le benchmark plante.

Prérequis de sécurité :
- la clé temporaire doit permettre la suppression GraphQL des Pods ;
- vérifier avant location qu'une suppression d'ID fictif répond `not_found`, pas `forbidden` ;
- ce watchdog doit être lancé AVANT le workload et rester vivant à côté.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from rag_hermes.pod_budget import plan_pod_budget
from rag_hermes.pod_watchdog import (
    decide_watchdog_action,
    fallback_after_list_error,
    parse_pod_list_payload,
    parse_utc,
    publish_ready_marker,
)


def finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise argparse.ArgumentTypeError("must be a finite number")
    return parsed


def list_pods() -> list[dict]:
    result = subprocess.run(
        ["runpodctl", "pod", "list", "--all", "--output", "json"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pod list failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    return parse_pod_list_payload(payload)


def delete_pod(pod_id: str) -> None:
    result = subprocess.run(
        ["runpodctl", "pod", "delete", pod_id],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0 and "not_found" not in result.stderr:
        raise RuntimeError(f"pod delete failed for {pod_id}: {result.stderr.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="exact pod name to guard")
    parser.add_argument("--created-after", required=True, help="ISO8601 UTC lower bound")
    parser.add_argument("--hourly-rate-usd", type=finite_float, required=True)
    parser.add_argument("--max-duration-minutes", type=int, required=True)
    parser.add_argument("--max-total-cost-usd", type=finite_float, required=True)
    parser.add_argument("--provider-deadline", required=True)
    parser.add_argument("--max-delete-attempts", type=int, default=3)
    parser.add_argument(
        "--ready-file", type=Path, required=True,
        help="new file created only after the initial pod snapshot succeeds",
    )
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args()

    created_after = parse_utc(args.created_after)
    plan = plan_pod_budget(
        hourly_rate_usd=args.hourly_rate_usd,
        max_duration_minutes=args.max_duration_minutes,
        max_total_cost_usd=args.max_total_cost_usd,
        starts_at=created_after,
    )
    deadline = parse_utc(plan.terminate_after)
    provider_deadline = parse_utc(args.provider_deadline)
    if provider_deadline <= deadline:
        raise ValueError("provider deadline must be later than the watchdog deadline")
    if args.max_delete_attempts < 1 or args.poll_seconds < 1:
        raise ValueError("retry and polling bounds must be positive")
    initial_pods = list_pods()
    preexisting_ids = {
        str(pod["id"])
        for pod in initial_pods
        if pod.get("name") == args.name and pod.get("id")
    }
    if preexisting_ids:
        print(json.dumps({
            "event": "preexisting_name_conflict",
            "name": args.name,
            "pod_ids": sorted(preexisting_ids),
        }), flush=True)
        return 2

    armed_event = {
        "event": "watchdog_armed",
        "name": args.name,
        "created_after": args.created_after,
        "terminate_after": plan.terminate_after,
        "provider_deadline": provider_deadline.isoformat(),
        "max_delete_attempts": args.max_delete_attempts,
        "estimated_compute_cost_usd": plan.estimated_compute_cost_usd,
    }
    publish_ready_marker(args.ready_file, armed_event)
    print(json.dumps(armed_event), flush=True)

    observed_id: str | None = None
    deletion_requested = False
    absence_confirmations = 0
    delete_attempts = 0
    retries_exhausted_reported = False
    while True:
        now = datetime.now(timezone.utc)
        try:
            pods = list_pods()
            action, pod_id, observed_id = decide_watchdog_action(
                pods,
                args.name,
                preexisting_ids,
                observed_id,
                deadline,
                now,
                deletion_requested=deletion_requested,
                absence_confirmations=absence_confirmations,
                provider_deadline=provider_deadline,
                delete_attempts=delete_attempts,
                max_delete_attempts=args.max_delete_attempts,
            )
            if action in {"confirm_absence", "confirm_unobserved"}:
                absence_confirmations += 1
            elif observed_id and any(str(pod["id"]) == observed_id for pod in pods):
                absence_confirmations = 0
        except Exception as exc:
            print(json.dumps({"event": "list_error", "error": str(exc)}), flush=True)
            if now >= provider_deadline:
                print(json.dumps({
                    "event": "unconfirmed_at_provider_deadline",
                    "pod_id": observed_id,
                    "delete_attempts": delete_attempts,
                    "at": now.isoformat(),
                }), flush=True)
                return 3
            fallback_action, fallback_pod_id = fallback_after_list_error(
                observed_id, deadline, now
            )
            if fallback_action == "delete" and fallback_pod_id:
                if delete_attempts >= args.max_delete_attempts:
                    if not retries_exhausted_reported:
                        print(json.dumps({
                            "event": "delete_retries_exhausted_monitoring",
                            "pod_id": fallback_pod_id,
                            "delete_attempts": delete_attempts,
                        }), flush=True)
                        retries_exhausted_reported = True
                else:
                    delete_attempts += 1
                    try:
                        delete_pod(fallback_pod_id)
                        deletion_requested = True
                        print(json.dumps({
                            "event": "deleted_after_list_error",
                            "pod_id": fallback_pod_id,
                            "delete_attempt": delete_attempts,
                            "at": now.isoformat(),
                        }), flush=True)
                    except Exception as delete_exc:
                        print(json.dumps({
                            "event": "delete_error_after_list_error",
                            "pod_id": fallback_pod_id,
                            "delete_attempt": delete_attempts,
                            "error": str(delete_exc),
                        }), flush=True)
            elif fallback_action == "fatal_unobserved":
                print(json.dumps({
                    "event": "watchdog_blind_at_deadline",
                    "error": (
                        "pod list unavailable and no guarded pod id was observed; "
                        "continuing retries"
                    ),
                }), flush=True)
            time.sleep(args.poll_seconds)
            continue

        if action == "delete" and pod_id:
            delete_attempts += 1
            try:
                delete_pod(pod_id)
                deletion_requested = True
                print(json.dumps({
                    "event": "deleted",
                    "pod_id": pod_id,
                    "delete_attempt": delete_attempts,
                    "at": now.isoformat(),
                }), flush=True)
            except Exception as exc:
                print(json.dumps({
                    "event": "delete_error",
                    "pod_id": pod_id,
                    "delete_attempt": delete_attempts,
                    "error": str(exc),
                }), flush=True)
        elif action == "monitor_after_delete_retries":
            if not retries_exhausted_reported:
                print(json.dumps({
                    "event": "delete_retries_exhausted_monitoring",
                    "pod_id": observed_id,
                    "delete_attempts": delete_attempts,
                }), flush=True)
                retries_exhausted_reported = True
        elif action == "confirmed_absent":
            print(json.dumps({"event": "confirmed_absent", "pod_id": observed_id, "at": now.isoformat()}), flush=True)
            return 0
        elif action == "never_observed":
            print(json.dumps({"event": "never_observed", "at": now.isoformat()}), flush=True)
            return 2
        elif action == "unconfirmed_at_provider_deadline":
            print(json.dumps({
                "event": "unconfirmed_at_provider_deadline",
                "pod_id": observed_id,
                "delete_attempts": delete_attempts,
                "absence_confirmations": absence_confirmations,
                "at": now.isoformat(),
            }), flush=True)
            return 3

        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
