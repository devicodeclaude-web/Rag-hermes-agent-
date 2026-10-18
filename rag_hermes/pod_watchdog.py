from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable


def parse_pod_list_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        if "error" in payload:
            raise ValueError("malformed pod list response: error envelope")
        if "status" in payload and payload["status"] != "success":
            raise ValueError("malformed pod list response: failure status")
        if "pods" in payload and "data" in payload:
            raise ValueError("malformed pod list response: ambiguous pods/data envelope")
        if set(payload) not in ({"pods"}, {"data"}):
            raise ValueError(
                "malformed pod list response: envelope must contain exactly pods or data"
            )
        if "pods" in payload:
            pods = payload["pods"]
        elif "data" in payload:
            pods = payload["data"]
        else:
            raise ValueError("malformed pod list response: missing pods/data list")
    elif isinstance(payload, list):
        pods = payload
    else:
        raise ValueError("malformed pod list response: expected list or object")
    if not isinstance(pods, list) or any(not isinstance(pod, dict) for pod in pods):
        raise ValueError("malformed pod list response: pod collection must be a list of objects")
    for pod in pods:
        if (
            not isinstance(pod.get("id"), str)
            or not pod["id"].strip()
            or not isinstance(pod.get("name"), str)
            or not pod["name"].strip()
        ):
            raise ValueError(
                "malformed pod list response: every pod requires non-empty string id and name"
            )
    return pods


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def select_guarded_pod(
    pods: Iterable[dict[str, Any]],
    exact_name: str,
    created_after: datetime,
) -> dict[str, Any] | None:
    if not exact_name:
        raise ValueError("exact pod name is required")
    if created_after.tzinfo is None:
        raise ValueError("created_after must be timezone-aware")
    boundary = created_after.astimezone(timezone.utc)
    matches = [
        pod
        for pod in pods
        if pod.get("name") == exact_name
        and pod.get("id")
        and pod.get("createdAt")
        and parse_utc(str(pod["createdAt"])) >= boundary
    ]
    if len(matches) > 1:
        raise RuntimeError("multiple pods match the guarded campaign; refusing deletion")
    return matches[0] if matches else None


def select_new_guarded_pod(
    pods: Iterable[dict[str, Any]],
    exact_name: str,
    preexisting_ids: set[str],
) -> dict[str, Any] | None:
    if not exact_name:
        raise ValueError("exact pod name is required")
    matches = [
        pod
        for pod in pods
        if pod.get("name") == exact_name and pod.get("id")
    ]
    if any(str(pod["id"]) in preexisting_ids for pod in matches):
        raise RuntimeError("a pre-existing pod matches the guarded campaign")
    if len(matches) > 1:
        raise RuntimeError("multiple pods match the guarded campaign; refusing deletion")
    return matches[0] if matches else None


def decide_watchdog_action(
    pods: Iterable[dict[str, Any]],
    exact_name: str,
    preexisting_ids: set[str],
    observed_id: str | None,
    deadline: datetime,
    now: datetime,
    deletion_requested: bool = False,
    absence_confirmations: int = 0,
    required_absence_confirmations: int = 2,
    provider_deadline: datetime | None = None,
    delete_attempts: int = 0,
    max_delete_attempts: int = 3,
) -> tuple[str, str | None, str | None]:
    if absence_confirmations < 0 or required_absence_confirmations < 2:
        raise ValueError("absence confirmation counts are invalid")
    if delete_attempts < 0 or max_delete_attempts < 1:
        raise ValueError("delete attempt counts are invalid")
    if provider_deadline is not None and provider_deadline.tzinfo is None:
        raise ValueError("provider deadline must be timezone-aware")
    pod = select_new_guarded_pod(pods, exact_name, preexisting_ids)
    current_id = str(pod["id"]) if pod else None
    if observed_id and current_id and current_id != observed_id:
        raise RuntimeError("guarded pod id changed; refusing deletion")
    seen_id = observed_id or current_id
    deadline_reached = now.astimezone(timezone.utc) >= deadline.astimezone(timezone.utc)
    provider_deadline_reached = (
        provider_deadline is not None
        and now.astimezone(timezone.utc) >= provider_deadline.astimezone(timezone.utc)
    )
    if provider_deadline_reached:
        if current_id or (seen_id and not deletion_requested):
            return "unconfirmed_at_provider_deadline", None, seen_id
        if seen_id and deletion_requested:
            if absence_confirmations + 1 >= required_absence_confirmations:
                return "confirmed_absent", None, seen_id
            return "unconfirmed_at_provider_deadline", None, seen_id
        if absence_confirmations + 1 >= required_absence_confirmations:
            return "never_observed", None, None
        return "unconfirmed_at_provider_deadline", None, None
    if current_id and deadline_reached:
        if delete_attempts >= max_delete_attempts:
            return "monitor_after_delete_retries", None, seen_id
        return "delete", current_id, seen_id
    if current_id:
        return "wait", None, seen_id
    if seen_id and deletion_requested:
        if absence_confirmations + 1 >= required_absence_confirmations:
            return "confirmed_absent", None, seen_id
        return "confirm_absence", None, seen_id
    if seen_id and deadline_reached:
        if delete_attempts >= max_delete_attempts:
            return "monitor_after_delete_retries", None, seen_id
        return "delete", seen_id, seen_id
    if seen_id:
        return "wait", None, seen_id
    if deadline_reached:
        if provider_deadline is None:
            return "never_observed", None, None
        return "confirm_unobserved", None, None
    return "wait", None, None


def fallback_after_list_error(
    observed_id: str | None,
    deadline: datetime,
    now: datetime,
) -> tuple[str, str | None]:
    if deadline.tzinfo is None or now.tzinfo is None:
        raise ValueError("deadline and now must be timezone-aware")
    if now.astimezone(timezone.utc) < deadline.astimezone(timezone.utc):
        return "wait", None
    if observed_id:
        return "delete", observed_id
    return "fatal_unobserved", None


def publish_ready_marker(path: Path, payload: dict[str, Any]) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
    except FileExistsError as exc:
        raise FileExistsError(f"ready marker already exists: {path}") from exc


def new_pod_due_for_deletion(
    pods: Iterable[dict[str, Any]],
    exact_name: str,
    preexisting_ids: set[str],
    deadline: datetime,
    now: datetime,
) -> list[str]:
    if deadline.tzinfo is None or now.tzinfo is None:
        raise ValueError("deadline and now must be timezone-aware")
    pod = select_new_guarded_pod(pods, exact_name, preexisting_ids)
    if pod is None or now.astimezone(timezone.utc) < deadline.astimezone(timezone.utc):
        return []
    return [str(pod["id"])]


def pods_due_for_deletion(
    pods: Iterable[dict[str, Any]],
    exact_name: str,
    created_after: datetime,
    deadline: datetime,
    now: datetime,
) -> list[str]:
    if deadline.tzinfo is None or now.tzinfo is None:
        raise ValueError("deadline and now must be timezone-aware")
    pod = select_guarded_pod(pods, exact_name, created_after)
    if pod is None or now.astimezone(timezone.utc) < deadline.astimezone(timezone.utc):
        return []
    return [str(pod["id"])]
