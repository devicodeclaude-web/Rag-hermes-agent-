import unittest
from datetime import datetime, timezone

from rag_hermes.pod_budget import plan_pod_budget


class PodBudgetTests(unittest.TestCase):
    def test_plan_calculates_cost_and_termination_deadline(self):
        plan = plan_pod_budget(
            hourly_rate_usd=0.74,
            max_duration_minutes=30,
            max_total_cost_usd=0.50,
            starts_at=datetime(2026, 9, 20, 14, 0, tzinfo=timezone.utc),
        )

        self.assertAlmostEqual(plan.estimated_compute_cost_usd, 0.37)
        self.assertEqual(plan.terminate_after, "2026-09-20T14:30:00Z")

    def test_plan_rejects_cost_over_cap(self):
        with self.assertRaisesRegex(ValueError, "exceeds cost cap"):
            plan_pod_budget(
                hourly_rate_usd=0.74,
                max_duration_minutes=60,
                max_total_cost_usd=0.50,
            )

    def test_plan_requires_positive_hard_limits(self):
        for duration, cap in [(0, 1.0), (30, 0.0)]:
            with self.subTest(duration=duration, cap=cap):
                with self.assertRaises(ValueError):
                    plan_pod_budget(
                        hourly_rate_usd=0.74,
                        max_duration_minutes=duration,
                        max_total_cost_usd=cap,
                    )


if __name__ == "__main__":
    unittest.main()
