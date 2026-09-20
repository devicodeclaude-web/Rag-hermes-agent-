from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


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
