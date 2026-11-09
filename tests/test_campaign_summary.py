from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rag_hermes.campaign_summary import build_campaign_summary

ROOT = Path(__file__).resolve().parents[1]


def retrieval(*, total=100, quality_eligible=False, security=True):
    return {
        "track": "synthetic",
        "provenance": "synthetic_generated_from_corpus",
        "quality_eligible": quality_eligible,
        "granularity": "document",
        "retriever": "in_memory_lexical_baseline",
        "k": 5,
        "cases_total": total,
        "metrics": {
            "case_count": total,
            "recall_at_k": 0.3,
            "mrr": 0.2,
            "citation_precision": 0.12,
            "abstention_precision": 0.0,
            "abstention_recall": 0.0,
            "leak_count": 0 if security else 1,
            "security_gate_passed": security,
            "acl_error_count": 0,
            "backend_error_count": 0,
        },
        "note": "TECHNICAL WITNESS ONLY",
    }


def comparison(*, total=100, sample=20):
    return {
        "track": "synthetic",
        "note": "OFFLINE comparison",
        "total": total,
        "review_fraction": 0.2,
        "review_sample_size": sample,
        "rag_abstention_precision": 0.0,
        "rag_abstention_recall": 0.0,
        "closed_book_abstention_precision": 0.2,
        "closed_book_abstention_recall": 1.0,
    }


def human(*, total=20, reviewed=20, complete=True):
    return {
        "complete_review": complete,
        "total": total,
        "reviewed": reviewed,
        "rag_accuracy": 0.65,
        "closed_book_accuracy": 0.35,
        "rag_better_count": 8,
        "closed_book_better_count": 2,
    }


class CampaignSummaryTests(unittest.TestCase):
    def test_missing_human_review_is_blocked_not_quality_evidence(self):
        report = build_campaign_summary(retrieval(), comparison(), None)
        self.assertEqual(report["status"], "BLOCKED_human_review_missing")
        self.assertFalse(report["quality_evidence"])
        self.assertEqual(report["human_correctness"]["status"], "missing")
        self.assertEqual(report["retrieval_technical"]["recall_at_k"], 0.3)
        self.assertEqual(report["abstention_comparison"]["review_sample_size"], 20)

    def test_complete_human_review_does_not_upgrade_legacy_metrics(self):
        report = build_campaign_summary(retrieval(), comparison(), human())
        self.assertEqual(report["status"], "BLOCKED_legacy_metrics_missing")
        self.assertFalse(report["quality_evidence"])
        self.assertEqual(report["retrieval_technical"]["metrics_contract"], "legacy_missing_failure_bounds")
        self.assertIsNone(report["retrieval_technical"]["citation_precision_lower_bound"])
        self.assertIsNone(report["security_gate_passed"])
        self.assertEqual(report["human_correctness"]["status"], "complete")
        self.assertEqual(report["human_correctness"]["reviewed"], 20)
        self.assertEqual(report["human_correctness"]["rag_accuracy"], 0.65)

    def test_partial_human_review_is_explicitly_blocked(self):
        report = build_campaign_summary(
            retrieval(), comparison(), human(reviewed=7, complete=False)
        )
        self.assertEqual(report["status"], "BLOCKED_human_review_incomplete")
        self.assertEqual(report["human_correctness"]["status"], "partial")
        self.assertEqual(report["human_correctness"]["reviewed"], 7)

    def test_security_failure_overrides_review_completion(self):
        report = build_campaign_summary(
            retrieval(security=False), comparison(), human()
        )
        self.assertEqual(report["status"], "FAILED_security_gate")
        self.assertFalse(report["security_gate_passed"])

    def test_incomplete_campaign_propagates_inconclusive_bounds_and_error_counts(self):
        source = retrieval()
        source["metrics"].update(
            case_count=100, executed_case_count=99,
            acl_error_count=1, backend_error_count=0,
            security_gate_passed=False,
            abstention_precision_lower_bound=0.0,
            citation_precision_lower_bound=None,
            citation_validity_precision_lower_bound=None,
            citation_support_precision_lower_bound=None,
        )
        report = build_campaign_summary(source, comparison(), human())
        self.assertEqual(report["status"], "FAILED_security_gate")
        technical = report["retrieval_technical"]
        self.assertEqual(technical["metrics_contract"], "failure_bounds_v2")
        self.assertEqual(technical["executed_case_count"], 99)
        self.assertEqual(technical["acl_error_count"], 1)
        self.assertEqual(technical["abstention_precision_lower_bound"], 0.0)
        self.assertIsNone(technical["citation_precision_lower_bound"])
        self.assertIsNone(technical["citation_validity_precision_lower_bound"])
        self.assertIsNone(technical["citation_support_precision_lower_bound"])

    def test_complete_modern_campaign_remains_only_a_synthetic_technical_witness(self):
        source = retrieval()
        source["metrics"].update(
            case_count=100, executed_case_count=100,
            acl_error_count=0, backend_error_count=0,
            abstention_precision_lower_bound=0.0,
            citation_precision_lower_bound=0.12,
            citation_validity_precision_lower_bound=None,
            citation_support_precision_lower_bound=None,
        )
        report = build_campaign_summary(source, comparison(), human())
        self.assertEqual(report["status"], "COMPLETE_synthetic_technical_witness")
        self.assertFalse(report["quality_evidence"])
        self.assertTrue(report["security_gate_passed"])
        self.assertEqual(report["retrieval_technical"]["citation_precision_lower_bound"], 0.12)

    def test_partial_new_metrics_contract_is_rejected_not_downgraded_to_legacy(self):
        source = retrieval()
        source["metrics"]["executed_case_count"] = 100
        with self.assertRaisesRegex(ValueError, "partial metrics contract"):
            build_campaign_summary(source, comparison(), human())

    def test_modern_report_cannot_certify_security_with_failed_cases(self):
        source = retrieval()
        source["metrics"].update(
            case_count=100, executed_case_count=99,
            acl_error_count=1, backend_error_count=0,
            abstention_precision_lower_bound=0.0,
            citation_precision_lower_bound=None,
            citation_validity_precision_lower_bound=None,
            citation_support_precision_lower_bound=None,
        )
        with self.assertRaisesRegex(ValueError, "inconsistent security gate"):
            build_campaign_summary(source, comparison(), human())

    def test_incomplete_campaign_cannot_publish_numeric_citation_bound(self):
        source = retrieval(security=False)
        source["metrics"].update(
            case_count=100, executed_case_count=99,
            acl_error_count=0, backend_error_count=1,
            abstention_precision_lower_bound=0.0,
            citation_precision_lower_bound=1.0,
            citation_validity_precision_lower_bound=None,
            citation_support_precision_lower_bound=None,
        )
        with self.assertRaisesRegex(ValueError, "inconclusive citation bounds"):
            build_campaign_summary(source, comparison(), human())

    def test_modern_report_rejects_a_bound_above_its_point_estimate(self):
        source = retrieval()
        source["metrics"].update(
            case_count=100, executed_case_count=100,
            acl_error_count=0, backend_error_count=0,
            abstention_precision_lower_bound=0.0,
            citation_precision_lower_bound=0.9,
            citation_validity_precision_lower_bound=None,
            citation_support_precision_lower_bound=None,
        )
        with self.assertRaisesRegex(ValueError, "citation_precision_lower_bound"):
            build_campaign_summary(source, comparison(), human())

    def test_complete_modern_campaign_requires_legacy_citation_bound(self):
        source = retrieval()
        source["metrics"].update(
            case_count=100, executed_case_count=100,
            acl_error_count=0, backend_error_count=0,
            abstention_precision_lower_bound=0.0,
            citation_precision_lower_bound=None,
            citation_validity_precision_lower_bound=None,
            citation_support_precision_lower_bound=None,
        )
        with self.assertRaisesRegex(ValueError, "citation_precision_lower_bound"):
            build_campaign_summary(source, comparison(), human())

    def test_complete_modern_campaign_requires_strict_bounds_when_judgments_exist(self):
        source = retrieval()
        source["metrics"].update(
            case_count=100, executed_case_count=100,
            acl_error_count=0, backend_error_count=0,
            abstention_precision_lower_bound=0.0,
            citation_precision_lower_bound=0.12,
            citation_validity_precision=1.0,
            citation_support_precision=0.5,
            citation_validity_precision_lower_bound=None,
            citation_support_precision_lower_bound=None,
        )
        with self.assertRaisesRegex(ValueError, "citation_validity_precision_lower_bound"):
            build_campaign_summary(source, comparison(), human())

    def test_empty_campaign_cannot_certify_security_or_completeness(self):
        source = retrieval(total=0)
        source["metrics"].update(
            case_count=0, executed_case_count=0,
            acl_error_count=0, backend_error_count=0,
            abstention_precision_lower_bound=0.0,
            citation_precision_lower_bound=0.0,
            citation_validity_precision_lower_bound=None,
            citation_support_precision_lower_bound=None,
        )
        with self.assertRaisesRegex(ValueError, "non-empty campaign"):
            build_campaign_summary(source, comparison(total=0, sample=0), human(total=0, reviewed=0))

    def test_rejects_case_count_mismatch(self):
        with self.assertRaisesRegex(ValueError, "case count mismatch"):
            build_campaign_summary(retrieval(total=100), comparison(total=99), None)

    def test_rejects_human_sample_size_mismatch(self):
        with self.assertRaisesRegex(ValueError, "review sample size mismatch"):
            build_campaign_summary(
                retrieval(), comparison(sample=20), human(total=19)
            )

    def test_rejects_quality_eligible_input_in_synthetic_summary(self):
        with self.assertRaisesRegex(ValueError, "quality-eligible"):
            build_campaign_summary(
                retrieval(quality_eligible=True), comparison(), None
            )

    def test_rejects_inconsistent_complete_human_review(self):
        with self.assertRaisesRegex(ValueError, "complete human review"):
            build_campaign_summary(
                retrieval(), comparison(), human(reviewed=19, complete=True)
            )

    def test_cli_writes_blocked_report_when_human_aggregate_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            retrieval_path = root / "retrieval.json"
            comparison_path = root / "comparison.json"
            human_path = root / "missing-human.json"
            output_path = root / "summary.json"
            retrieval_path.write_text(json.dumps(retrieval()), encoding="utf-8")
            comparison_path.write_text(json.dumps(comparison()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/consolidate_campaign.py",
                    "--retrieval", str(retrieval_path),
                    "--comparison", str(comparison_path),
                    "--human", str(human_path),
                    "--out", str(output_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2, completed.stderr)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "BLOCKED_human_review_missing")
            self.assertFalse(report["quality_evidence"])


if __name__ == "__main__":
    unittest.main()
