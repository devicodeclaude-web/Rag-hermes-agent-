from __future__ import annotations

import unittest

import scripts.validate_dataset_v2 as v


class GateReportTests(unittest.TestCase):
    def test_remaining_counts_when_everything_is_short(self):
        # 10 EN cases, 2 complete FR pairs, 3 reviewed, targets 100 / 40.
        report = v.gate_report(
            total=10, en=10, fr=2, complete_pairs=2, reviewed=3,
            target_en=100, target_fr_pairs=40,
        )
        self.assertEqual(report["status"], "BLOCKED_review_or_volume")
        self.assertEqual(report["remaining"]["en2en_cases"], 90)      # 100 - 10
        self.assertEqual(report["remaining"]["fr_pairs"], 38)         # 40 - 2
        self.assertEqual(report["remaining"]["to_review"], 7)         # 10 - 3
        self.assertFalse(report["targets_met"])

    def test_remaining_is_zero_and_ready_when_targets_met(self):
        report = v.gate_report(
            total=100, en=100, fr=40, complete_pairs=40, reviewed=100,
            target_en=100, target_fr_pairs=40,
        )
        self.assertEqual(report["status"], "READY")
        self.assertTrue(report["targets_met"])
        self.assertEqual(report["remaining"]["en2en_cases"], 0)
        self.assertEqual(report["remaining"]["fr_pairs"], 0)
        self.assertEqual(report["remaining"]["to_review"], 0)

    def test_remaining_never_goes_negative_when_exceeding_targets(self):
        report = v.gate_report(
            total=120, en=120, fr=50, complete_pairs=50, reviewed=120,
            target_en=100, target_fr_pairs=40,
        )
        self.assertEqual(report["remaining"]["en2en_cases"], 0)  # not -20
        self.assertEqual(report["remaining"]["fr_pairs"], 0)     # not -10
        self.assertTrue(report["targets_met"])

    def test_report_preserves_existing_keys(self):
        # Backward compatibility: the historical keys must still be present.
        report = v.gate_report(
            total=5, en=4, fr=1, complete_pairs=1, reviewed=2,
            target_en=100, target_fr_pairs=40,
        )
        for key in (
            "total", "en2en", "fr2en", "complete_en_fr_pairs",
            "reviewed", "pending", "target_en", "target_fr_pairs",
            "structural", "status",
        ):
            self.assertIn(key, report)
        self.assertEqual(report["total"], 5)
        self.assertEqual(report["en2en"], 4)
        self.assertEqual(report["fr2en"], 1)
        self.assertEqual(report["pending"], 3)  # 5 - 2


if __name__ == "__main__":
    unittest.main()
