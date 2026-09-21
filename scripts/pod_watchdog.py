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
import subprocess
import sys
import time

from rag_hermes.pod_budget import plan_pod_budget
from rag_hermes.pod_watchdog import decide_watchdog_action, parse_utc


def list_pods() -> list[dict]:
    result = subprocess.run(
        ["runpodctl", "pod", "list", "--all", "--output", "json"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pod list failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout or "{}")
    if isinstance(payload, dict):
        return payload.get("pods") or payload.get("data") or []
    return payload if isinstance(payload, list) else []


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
    parser.add_argument("--hourly-rate-usd", type=float, required=True)
    parser.add_argument("--max-duration-minutes", type=int, required=True)
    parser.add_argument("--max-total-cost-usd", type=float, required=True)
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

    print(json.dumps({
        "event": "watchdog_armed",
        "name": args.name,
        "created_after": args.created_after,
        "terminate_after": plan.terminate_after,
        "estimated_compute_cost_usd": plan.estimated_compute_cost_usd,
    }), flush=True)

    observed_id: str | None = None
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
            )
        except Exception as exc:  # keep guarding despite transient list errors
            print(json.dumps({"event": "list_error", "error": str(exc)}), flush=True)
            time.sleep(args.poll_seconds)
            continue

        if action == "delete" and pod_id:
            try:
                delete_pod(pod_id)
                print(json.dumps({"event": "deleted", "pod_id": pod_id, "at": now.isoformat()}), flush=True)
            except Exception as exc:
                print(json.dumps({"event": "delete_error", "pod_id": pod_id, "error": str(exc)}), flush=True)
        elif action == "confirmed_absent":
            print(json.dumps({"event": "confirmed_absent", "pod_id": observed_id, "at": now.isoformat()}), flush=True)
            return 0
        elif action == "never_observed":
            print(json.dumps({"event": "never_observed", "at": now.isoformat()}), flush=True)
            return 2

        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
