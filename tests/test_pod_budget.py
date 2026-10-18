import unittest
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile

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

    def test_plan_rejects_non_finite_money_values(self):
        for field in ("hourly_rate_usd", "max_total_cost_usd"):
            for value in (float("nan"), float("inf"), float("-inf")):
                arguments = {
                    "hourly_rate_usd": 0.74,
                    "max_duration_minutes": 30,
                    "max_total_cost_usd": 0.50,
                }
                arguments[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, f"{field} must be finite"):
                        plan_pod_budget(**arguments)

    def test_watchdog_argparse_rejects_non_finite_money_values(self):
        module = "scripts.pod_watchdog"
        for flag, value in (
            ("--hourly-rate-usd", "nan"),
            ("--hourly-rate-usd", "inf"),
            ("--hourly-rate-usd", "-inf"),
            ("--max-total-cost-usd", "nan"),
            ("--max-total-cost-usd", "inf"),
            ("--max-total-cost-usd", "-inf"),
        ):
            with self.subTest(flag=flag, value=value), tempfile.TemporaryDirectory() as directory:
                arguments = [
                    sys.executable,
                    "-m", module,
                    "--name", "guarded",
                    "--created-after", "2026-09-20T14:00:00Z",
                    f"--hourly-rate-usd={value if flag == '--hourly-rate-usd' else '0.74'}",
                    "--max-duration-minutes", "30",
                    f"--max-total-cost-usd={value if flag == '--max-total-cost-usd' else '0.50'}",
                    "--provider-deadline", "2026-09-20T14:31:00Z",
                    "--ready-file", str(Path(directory) / "ready.json"),
                ]
                completed = subprocess.run(arguments, capture_output=True, text=True)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("must be a finite number", completed.stderr)


if __name__ == "__main__":
    unittest.main()
