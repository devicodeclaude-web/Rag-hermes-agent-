"""Offline G1 input alignment; these tests do not exercise retrieval or generation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.preflight_g1_inputs import check_g1_inputs
from rag_hermes.closed_book import CLOSED_BOOK_ABSTENTION


class G1InputPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        dataset = self.root / "data/benchmark/dataset-v2-human-154.jsonl"
        dataset.parent.mkdir(parents=True)
        self.ids = [f"case-{i:03}" for i in range(154)]
        dataset.write_text("".join(json.dumps({"case_id": cid, "question": cid, "should_abstain": False}) + "\n" for cid in self.ids), encoding="utf-8")
        self.dataset_sha = hashlib.sha256(dataset.read_bytes()).hexdigest()
        manifest = self.root / "manifests/gpu/g0-closed-book-human-154.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"classification": "infrastructure_smoke_only",
            "protocol": {"configuration": "G0"}, "generator": {
            "repo_id": "Qwen/Qwen2.5-7B-Instruct", "revision": "pinned-revision",
            "engine": "vllm", "quantization": "none",
            "served_model_name": "qwen2.5-7b-instruct", "decoding": {"temperature": 0, "max_tokens": 512},
        }, "corpus": {"questions": "data/benchmark/dataset-v2-human-154.jsonl"}}), encoding="utf-8")
        self.manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
        retrieval_manifest = self.root / "manifests/gpu/bge-m3-human-154.json"
        retrieval_manifest.write_text(json.dumps({"corpus": {"questions": "data/benchmark/dataset-v2-human-154.jsonl"}}), encoding="utf-8")
        self.retrieval_manifest_sha = hashlib.sha256(retrieval_manifest.read_bytes()).hexdigest()
        self.bge_report = {"status": "intermediate_human_component_evaluation",
                           "code_revision": "a" * 40, "audited_commit": "a" * 40,
            "protocol": {"dataset_path": "data/benchmark/dataset-v2-human-154.jsonl", "dataset_sha256": self.dataset_sha,
                         "manifest_path": "manifests/gpu/bge-m3-human-154.json", "manifest_sha256": self.retrieval_manifest_sha},
            "cases": [{"case_id": cid} for cid in self.ids]}
        self.g0_report = {"configuration": "G0", "status": "infrastructure_smoke_only",
                          "code_revision": "b" * 40, "audited_commit": "b" * 40,
            "protocol": {"dataset_path": "data/benchmark/dataset-v2-human-154.jsonl", "dataset_sha256": self.dataset_sha,
                         "manifest_path": "manifests/gpu/g0-closed-book-human-154.json", "manifest_sha256": self.manifest_sha},
            "generator": {"repo_id": "Qwen/Qwen2.5-7B-Instruct", "revision": "pinned-revision",
                          "engine": "vllm", "quantization": "none",
                          "served_model_name": "qwen2.5-7b-instruct", "decoding": {"temperature": 0, "max_tokens": 512}},
            "generation": {"temperature": 0, "max_tokens": 512},
            "result_classification": "g0_closed_book_abstention_wiring_not_a_quality_benchmark",
            "quality_gate_passed": False,
            "corpus": {"questions": 154, "track": "human-154",
                       "dataset_path": "data/benchmark/dataset-v2-human-154.jsonl"},
            "human_review_sample": {"answered_count": 154, "answered_case_ids": self.ids.copy()},
            "metrics_abstention": {"generation_failures": 0, "total": 154,
                                    "required_abstentions": 0, "predicted_abstentions": 0,
                                    "true_positive_abstentions": 0,
                                    "abstention_precision": 0.0, "abstention_recall": 0.0},
            "answer_records": [{"case_id": cid, "question": cid, "answer": "sample", "did_abstain": False, "should_abstain": False} for cid in self.ids]}
        self.write_receipt("bge_m3_human_154_execution_receipt.json", self.bge_report)

    def write_receipt(self, filename: str, report: dict) -> None:
        path = self.root / "data/results" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        receipt = {"schema_version": "gpu_execution_receipt.v2", "status": "completed",
            "started_utc": "2026-11-01T00:00:00Z", "finished_utc": "2026-11-01T00:01:00Z",
            "command": ["python", "worker.py"], "cwd": "/workspace", "environment": {}, "exit_code": 0,
            "report": report, "report_encoding": "canonical-json-utf8",
            "report_sha256_scope": "receipt.report canonical-json-utf8",
            "report_sha256": hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        path.write_text(json.dumps(receipt), encoding="utf-8")

    def test_missing_g0_receipt_blocks_alignment(self) -> None:
        result = check_g1_inputs(self.root)
        self.assertFalse(result["inputs_aligned"])
        self.assertIn("missing_verified_g0_receipt", result["blockers"])
        self.assertEqual(result["dataset_cases"], 154)

    def test_verified_g0_and_retrieval_inputs_align(self) -> None:
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        result = check_g1_inputs(self.root)
        self.assertTrue(result["inputs_aligned"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["scope"], "input_alignment_only_not_g1_readiness")

    def test_consistent_abstention_capture_aligns(self) -> None:
        dataset = self.root / "data/benchmark/dataset-v2-human-154.jsonl"
        rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]
        rows[0]["should_abstain"] = True
        dataset.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        sha = hashlib.sha256(dataset.read_bytes()).hexdigest()
        self.bge_report["protocol"]["dataset_sha256"] = sha
        self.write_receipt("bge_m3_human_154_execution_receipt.json", self.bge_report)
        self.g0_report["protocol"]["dataset_sha256"] = sha
        self.g0_report["answer_records"][0].update({
            "should_abstain": True, "did_abstain": True, "answer": CLOSED_BOOK_ABSTENTION
        })
        self.g0_report["metrics_abstention"].update({
            "required_abstentions": 1, "predicted_abstentions": 1,
            "true_positive_abstentions": 1, "abstention_precision": 1.0,
            "abstention_recall": 1.0
        })
        self.g0_report["human_review_sample"].update({
            "answered_count": 153, "answered_case_ids": self.ids[1:]
        })
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertTrue(check_g1_inputs(self.root)["inputs_aligned"])

    def test_tampered_receipt_cannot_be_aligned(self) -> None:
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        path = self.root / "data/results/g0_closed_book_human_154_execution_receipt.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["report"]["answer_records"][0]["answer"] = "tampered"
        path.write_text(json.dumps(payload), encoding="utf-8")
        result = check_g1_inputs(self.root)
        self.assertFalse(result["inputs_aligned"])
        self.assertIn("invalid_g0_receipt", result["blockers"])

    def test_dataset_hash_mismatch_blocks_alignment(self) -> None:
        self.g0_report["protocol"]["dataset_sha256"] = "0" * 64
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        result = check_g1_inputs(self.root)
        self.assertFalse(result["inputs_aligned"])
        self.assertIn("g0_dataset_mismatch", result["blockers"])

    def test_incomplete_answer_capture_blocks_alignment(self) -> None:
        self.g0_report["answer_records"] = self.g0_report["answer_records"][:-1]
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        result = check_g1_inputs(self.root)
        self.assertFalse(result["inputs_aligned"])
        self.assertIn("g0_answer_capture_incomplete", result["blockers"])

    def test_empty_answer_text_blocks_alignment(self) -> None:
        self.g0_report["answer_records"][0]["answer"] = "  "
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["g0_answer_capture_incomplete"])

    def test_abstention_text_disagrees_with_flag_blocks_alignment(self) -> None:
        self.g0_report["answer_records"][0]["answer"] = CLOSED_BOOK_ABSTENTION
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["g0_answer_capture_incomplete"])

    def test_answer_capture_question_mismatch_blocks_alignment(self) -> None:
        self.g0_report["answer_records"][0]["question"] = "another question"
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        result = check_g1_inputs(self.root)
        self.assertIn("g0_answer_capture_incomplete", result["blockers"])

    def test_generator_revision_mismatch_blocks_alignment(self) -> None:
        self.g0_report["generator"]["revision"] = "wrong-revision"
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        result = check_g1_inputs(self.root)
        self.assertFalse(result["inputs_aligned"])
        self.assertIn("g0_generator_pin_mismatch", result["blockers"])

    def test_g0_report_manifest_hash_mismatch_blocks_alignment(self) -> None:
        self.g0_report["protocol"]["manifest_sha256"] = "0" * 64
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertIn("g0_manifest_mismatch", check_g1_inputs(self.root)["blockers"])

    def test_retrieval_report_manifest_path_mismatch_blocks_alignment(self) -> None:
        self.bge_report["protocol"]["manifest_path"] = "another.json"
        self.write_receipt("bge_m3_human_154_execution_receipt.json", self.bge_report)
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertIn("retrieval_manifest_mismatch", check_g1_inputs(self.root)["blockers"])

    def test_generation_section_must_match_decoding_pin(self) -> None:
        self.g0_report["generation"]["temperature"] = 1
        self.g0_report["generation"]["max_tokens"] = 1
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["g0_generator_pin_mismatch"])

    def test_manifest_configuration_g1_blocks_g0_alignment(self) -> None:
        path = self.root / "manifests/gpu/g0-closed-book-human-154.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["protocol"]["configuration"] = "G1"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.g0_report["protocol"]["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["g0_manifest_configuration_mismatch"])

    def test_manifest_quality_claim_blocks_g0_alignment(self) -> None:
        path = self.root / "manifests/gpu/g0-closed-book-human-154.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["classification"] = "quality_benchmark"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.g0_report["protocol"]["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["g0_manifest_configuration_mismatch"])

    def test_nonstandard_nan_manifest_blocks_alignment(self) -> None:
        path = self.root / "manifests/gpu/g0-closed-book-human-154.json"
        raw = path.read_text(encoding="utf-8").rstrip()[:-1] + ', "invalid": NaN}'
        path.write_text(raw, encoding="utf-8")
        self.g0_report["protocol"]["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["invalid_g0_manifest"])

    def test_generator_engine_mismatch_blocks_alignment(self) -> None:
        self.g0_report["generator"]["engine"] = "different"
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertIn("g0_generator_pin_mismatch", check_g1_inputs(self.root)["blockers"])

    def test_missing_identity_on_both_sides_blocks_alignment(self) -> None:
        manifest = self.root / "manifests/gpu/g0-closed-book-human-154.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        del data["generator"]["repo_id"]
        manifest.write_text(json.dumps(data), encoding="utf-8")
        self.g0_report["protocol"]["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
        del self.g0_report["generator"]["repo_id"]
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertIn("g0_generator_pin_mismatch", check_g1_inputs(self.root)["blockers"])

    def test_empty_code_revisions_block_alignment(self) -> None:
        self.bge_report["code_revision"] = self.bge_report["audited_commit"] = ""
        self.g0_report["code_revision"] = self.g0_report["audited_commit"] = ""
        self.write_receipt("bge_m3_human_154_execution_receipt.json", self.bge_report)
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        blockers = check_g1_inputs(self.root)["blockers"]
        self.assertIsInstance(blockers, list)
        self.assertIn("retrieval_revision_mismatch", blockers)
        self.assertIn("g0_revision_mismatch", blockers)

    def test_failed_retrieval_report_status_blocks_alignment(self) -> None:
        self.bge_report["status"] = "failed"
        self.write_receipt("bge_m3_human_154_execution_receipt.json", self.bge_report)
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["retrieval_report_status_mismatch"])

    def test_failed_report_status_blocks_alignment(self) -> None:
        self.g0_report["status"] = "failed"
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["g0_report_status_mismatch"])

    def test_abstention_metrics_disagree_with_records_blocks_alignment(self) -> None:
        self.g0_report["metrics_abstention"]["predicted_abstentions"] = 154
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["g0_answer_capture_incomplete"])

    def test_abstention_ratio_disagrees_with_records_blocks_alignment(self) -> None:
        self.g0_report["metrics_abstention"]["abstention_precision"] = 1.0
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["g0_answer_capture_incomplete"])

    def test_quality_gate_claim_blocks_infrastructure_only_alignment(self) -> None:
        self.g0_report["quality_gate_passed"] = True
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["g0_classification_mismatch"])

    def test_missing_report_corpus_blocks_alignment(self) -> None:
        del self.g0_report["corpus"]
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["g0_corpus_mismatch"])

    def test_review_sample_disagrees_with_capture_blocks_alignment(self) -> None:
        self.g0_report["human_review_sample"]["answered_count"] = 0
        self.g0_report["human_review_sample"]["answered_case_ids"] = []
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertEqual(check_g1_inputs(self.root)["blockers"], ["g0_review_sample_mismatch"])

    def test_reported_generation_failures_contradict_full_capture(self) -> None:
        self.g0_report["metrics_abstention"]["generation_failures"] = 154
        self.write_receipt("g0_closed_book_human_154_execution_receipt.json", self.g0_report)
        self.assertIn("g0_answer_capture_incomplete", check_g1_inputs(self.root)["blockers"])


if __name__ == "__main__":
    unittest.main()
