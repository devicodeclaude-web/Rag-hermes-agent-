"""G0 closed-book runner — wiring tests (no GPU, no network).

Validate that the G0 worker projects the human-154 rows correctly, that the
closed-book abstention scoring flows into an honest report, and that provider
failures are counted as neither answers nor abstentions.
"""
import json
import unittest
from pathlib import Path

from rag_hermes.closed_book import CLOSED_BOOK_ABSTENTION, GenerationError
from rag_hermes.closed_book_eval import run_closed_book_evaluation
from scripts import run_closed_book_g0 as g0

HUMAN_154 = Path("data/benchmark/dataset-v2-human-154.jsonl")
_REVISION = "0" * 40


def _report_for(cases, generator):
    report = run_closed_book_evaluation(cases, generator)
    return g0.build_g0_report(
        manifest={
            "job_id": "g0-test",
            "protocol": {
                "evaluation_protocol": "docs/evaluation-protocol-v2.md",
                "evaluation_protocol_status": "DRAFT_not_frozen_run_is_not_pre_registered",
                "acceptance_criteria": "docs/acceptance-criteria.md",
            },
        },
        manifest_path="manifests/gpu/g0-closed-book-human-154.json",
        manifest_sha256="a" * 64,
        code_revision=_REVISION,
        dataset_attestation={"path": "data/benchmark/dataset-v2-human-154.jsonl", "sha256": "b" * 64},
        generator_identity={"repo_id": "Qwen/Qwen2.5-7B-Instruct", "revision": "a09a3545"},
        report=report,
        generation_seconds=1.0,
    )


class LoadCasesTests(unittest.TestCase):
    def test_projects_real_human154_triples(self):
        cases = g0.load_cases(HUMAN_154.read_bytes())
        self.assertEqual(len(cases), 154)
        self.assertEqual(len({c["case_id"] for c in cases}), 154)
        self.assertTrue(all(c["question"] for c in cases))
        self.assertTrue(all(type(c["should_abstain"]) is bool for c in cases))
        self.assertEqual(sum(1 for c in cases if c["should_abstain"]), 32)

    def test_rejects_non_bool_should_abstain(self):
        payload = json.dumps(
            {"case_id": "x", "question": "q", "should_abstain": "true"}
        ).encode()
        with self.assertRaises(ValueError):
            g0.load_cases(payload)

    def test_rejects_empty_dataset(self):
        with self.assertRaises(ValueError):
            g0.load_cases(b"\n  \n")


class ReportTests(unittest.TestCase):
    def setUp(self):
        # Three answerable, two must-abstain.
        self.cases = [
            {"case_id": "a1", "question": "capital of France?", "should_abstain": False},
            {"case_id": "a2", "question": "capital of Spain?", "should_abstain": False},
            {"case_id": "a3", "question": "capital of Italy?", "should_abstain": False},
            {"case_id": "n1", "question": "countries in Africa?", "should_abstain": True},
            {"case_id": "n2", "question": "my private key?", "should_abstain": True},
        ]
        self._abstain_q = {"countries in Africa?", "my private key?"}

    def test_perfect_baseline_scores_and_is_honest(self):
        def perfect(question: str) -> str:
            return CLOSED_BOOK_ABSTENTION if question in self._abstain_q else "An answer."

        report = _report_for(self.cases, perfect)
        m = report["metrics_abstention"]
        self.assertEqual(m["total"], 5)
        self.assertEqual(m["required_abstentions"], 2)
        self.assertEqual(m["predicted_abstentions"], 2)
        self.assertEqual(m["true_positive_abstentions"], 2)
        self.assertEqual(m["abstention_precision"], 1.0)
        self.assertEqual(m["abstention_recall"], 1.0)
        self.assertEqual(m["generation_failures"], 0)
        # answered = the 3 answerable cases, surfaced for human review
        self.assertEqual(report["human_review_sample"]["answered_count"], 3)
        self.assertEqual(
            set(report["human_review_sample"]["answered_case_ids"]),
            {"a1", "a2", "a3"},
        )
        # honest classification, never a quality claim
        self.assertEqual(report["configuration"], "G0")
        self.assertEqual(report["status"], "infrastructure_smoke_only")
        self.assertEqual(
            report["result_classification"],
            "g0_closed_book_abstention_wiring_not_a_quality_benchmark",
        )
        self.assertFalse(report["quality_gate_passed"])
        self.assertEqual(
            report["protocol"]["evaluation_protocol_status"],
            "DRAFT_not_frozen_run_is_not_pre_registered",
        )
        self.assertTrue(report["limitations"])
        # fully JSON serializable
        json.dumps(report)

    def test_always_answering_model_has_zero_abstention(self):
        report = _report_for(self.cases, lambda q: "Always something.")
        m = report["metrics_abstention"]
        self.assertEqual(m["predicted_abstentions"], 0)
        self.assertEqual(m["abstention_precision"], 0.0)
        self.assertEqual(m["abstention_recall"], 0.0)
        self.assertEqual(report["human_review_sample"]["answered_count"], 5)

    def test_provider_failures_are_neither_answer_nor_abstention(self):
        def flaky(question: str) -> str:
            if question == "capital of Spain?":
                raise GenerationError("boom")
            return CLOSED_BOOK_ABSTENTION if question in self._abstain_q else "ok"

        report = _report_for(self.cases, flaky)
        m = report["metrics_abstention"]
        self.assertEqual(m["generation_failures"], 1)
        # a2 failed -> not answered, not abstained
        self.assertNotIn("a2", report["human_review_sample"]["answered_case_ids"])
        self.assertEqual(report["human_review_sample"]["answered_count"], 2)
        self.assertEqual(m["predicted_abstentions"], 2)


class ManifestContractTests(unittest.TestCase):
    def test_required_decoding_matches_closed_book_generator(self):
        self.assertEqual(g0._REQUIRED_DECODING, {"temperature": 0, "max_tokens": 512})

    def test_manifest_declares_matching_decoding_and_pinned_revision(self):
        manifest = json.loads(
            Path("manifests/gpu/g0-closed-book-human-154.json").read_text("utf-8")
        )
        gen = manifest["generator"]
        self.assertEqual(gen["decoding"], g0._REQUIRED_DECODING)
        self.assertEqual(gen["engine"], "vllm")
        self.assertRegex(gen["revision"], r"^[0-9a-f]{40}$")
        self.assertEqual(
            manifest["corpus"]["questions"], "data/benchmark/dataset-v2-human-154.jsonl"
        )
        self.assertEqual(manifest["classification"], "infrastructure_smoke_only")


if __name__ == "__main__":
    unittest.main()
