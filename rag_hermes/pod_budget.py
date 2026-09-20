from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class PodBudgetPlan:
    hourly_rate_usd: float
    max_duration_minutes: int
    max_total_cost_usd: float
    estimated_compute_cost_usd: float
    terminate_after: str


def plan_pod_budget(
    *,
    hourly_rate_usd: float,
    max_duration_minutes: int,
    max_total_cost_usd: float,
    starts_at: datetime | None = None,
) -> PodBudgetPlan:
    if hourly_rate_usd <= 0:
        raise ValueError("hourly_rate_usd must be positive")
    if max_duration_minutes <= 0:
        raise ValueError("max_duration_minutes must be positive")
    if max_total_cost_usd <= 0:
        raise ValueError("max_total_cost_usd must be positive")

    estimated_cost = hourly_rate_usd * max_duration_minutes / 60
    if estimated_cost > max_total_cost_usd:
        raise ValueError(
            f"estimated compute cost {estimated_cost:.4f} USD exceeds cost cap "
            f"{max_total_cost_usd:.4f} USD"
        )

    start = starts_at or datetime.now(timezone.utc)
    if start.tzinfo is None:
        raise ValueError("starts_at must be timezone-aware")
    deadline = start.astimezone(timezone.utc) + timedelta(minutes=max_duration_minutes)
    return PodBudgetPlan(
        hourly_rate_usd=hourly_rate_usd,
        max_duration_minutes=max_duration_minutes,
        max_total_cost_usd=max_total_cost_usd,
        estimated_compute_cost_usd=estimated_cost,
        terminate_after=deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
