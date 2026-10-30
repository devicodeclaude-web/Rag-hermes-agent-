from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rag_hermes.acl import Chunk
from rag_hermes.abstention_calibration import (
    calibrate_threshold,
    deterministic_group_split,
    gpu_execution_metadata,
    gpu_report_limitations,
    human_cases_to_questions,
    human_evidence_counts,
    invalidate_gpu_output,
    publish_gpu_report_atomic,
    read_attested_json,
    read_clean_repository_revision,
    read_model_lock_snapshots,
    read_repository_json_snapshot,
    read_repository_snapshot,
    repository_file_attestation,
    require_clean_code_revision,
    require_code_revision,
    reranker_truncation_evidence,
    score_human_retrieval,
    score_threshold,
    validate_campaign_shape,
    validate_gpu_hardware,
    wilson_interval,
)


class AbstentionCalibrationTests(unittest.TestCase):
    def test_split_keeps_every_pair_on_one_side(self) -> None:
        cases = [
            {"case_id": "p1-en", "pair_id": "p1"},
            {"case_id": "p1-fr", "pair_id": "p1"},
            {"case_id": "p2-en", "pair_id": "p2"},
            {"case_id": "solo", "pair_id": None},
        ]

        split = deterministic_group_split(cases, salt="test-v1")

        self.assertEqual(split["p1-en"], split["p1-fr"])
        self.assertIn(split["p2-en"], {"calibration", "holdout"})
        self.assertIn(split["solo"], {"calibration", "holdout"})
        self.assertEqual(split, deterministic_group_split(cases, salt="test-v1"))

    def test_calibration_maximizes_balanced_accuracy_and_prefers_lower_threshold(self) -> None:
        calibration = [
            {"case_id": "a1", "should_abstain": True, "best_score": 0.10},
            {"case_id": "a2", "should_abstain": True, "best_score": 0.20},
            {"case_id": "q1", "should_abstain": False, "best_score": 0.80},
            {"case_id": "q2", "should_abstain": False, "best_score": 0.90},
        ]

        result = calibrate_threshold(calibration)

        self.assertGreater(result["threshold"], 0.20)
        self.assertLessEqual(result["threshold"], 0.80)
        self.assertEqual(result["objective"], "balanced_accuracy")
        self.assertEqual(result["metrics"]["balanced_accuracy"], 1.0)

    def test_calibration_refuses_a_single_class(self) -> None:
        with self.assertRaisesRegex(ValueError, "both abstention and answerable"):
            calibrate_threshold([
                {"case_id": "a1", "should_abstain": True, "best_score": 0.1}
            ])

    def test_wilson_interval_reports_uncertainty_at_extremes(self) -> None:
        zero = wilson_interval(0, 10)
        perfect = wilson_interval(10, 10)

        self.assertAlmostEqual(zero["low"], 0.0)
        self.assertAlmostEqual(zero["high"], 0.2775, places=4)
        self.assertAlmostEqual(perfect["low"], 0.7225, places=4)
        self.assertAlmostEqual(perfect["high"], 1.0)

    def test_score_threshold_treats_missing_score_as_abstention(self) -> None:
        rows = [
            {"case_id": "a", "should_abstain": True, "best_score": None},
            {"case_id": "b", "should_abstain": False, "best_score": 0.7},
        ]

        metrics = score_threshold(rows, threshold=0.5)

        self.assertEqual(metrics["true_positive_abstentions"], 1)
        self.assertEqual(metrics["true_negative_answers"], 1)
        self.assertEqual(metrics["balanced_accuracy"], 1.0)
    def test_human_cases_are_validated_and_mapped_to_public_questions(self) -> None:
        content = "alpha relevant passage omega"
        passage = "relevant passage"
        start = content.index(passage)
        documents = {
            "doc-1": {"content": content, "visibility": "public"},
        }
        manifest = {"source_revision": "abc1234", "corpus_manifest_sha": "f" * 64}
        base = {
            "case_id": "p1-en",
            "pair_id": "p1",
            "question": "What is relevant?",
            "language": "en",
            "track": "en2en",
            "category": "fact",
            "access_scope": "public",
            "question_provenance": "human_task_without_corpus_view",
            "should_abstain": False,
            "unanswerable_reason": None,
            "reference_status": "validated",
            "relevance_spans": [{
                "document_id": "doc-1",
                "start_char": start,
                "end_char": start + len(passage),
                "passage_sha256": hashlib.sha256(passage.encode()).hexdigest(),
                "relevance_grade": 2,
            }],
            **manifest,
        }

        validated, questions = human_cases_to_questions([base], documents, manifest)

        self.assertEqual(validated[0]["case_id"], "p1-en")
        self.assertEqual(questions[0].relevant_document_ids, ("doc-1",))
        self.assertEqual(questions[0].context.tenant_id, "public")

    def test_human_retrieval_scoring_uses_passage_overlap(self) -> None:
        content = "alpha relevant passage omega"
        passage = "relevant passage"
        start = content.index(passage)
        documents = {"doc-1": {"content": content, "visibility": "public"}}
        manifest = {"source_revision": "abc1234", "corpus_manifest_sha": "f" * 64}
        case = {
            "case_id": "p1-en", "pair_id": "p1", "question": "What is relevant?",
            "language": "en", "track": "en2en", "category": "fact",
            "access_scope": "public", "question_provenance": "human_task_without_corpus_view",
            "should_abstain": False, "unanswerable_reason": None,
            "reference_status": "validated", **manifest,
            "relevance_spans": [{
                "document_id": "doc-1", "start_char": start,
                "end_char": start + len(passage),
                "passage_sha256": hashlib.sha256(passage.encode()).hexdigest(),
                "relevance_grade": 2,
            }],
        }
        chunk = Chunk(
            chunk_id="c1", document_id="doc-1", text=passage,
            tenant_id="public", visibility="public", allowed_groups=(),
            allowed_users=(), owner_id="evaluator", classification=0,
            doc_version=1, source_sha="0" * 64,
            start_offset=start, end_offset=start + len(passage),
        )

        report = score_human_retrieval(
            [case], documents, manifest,
            {"p1-en": {"chunks": [chunk], "best_score": 0.9}},
            threshold=0.5, k=10,
        )

        self.assertEqual(report["recall_at_k"], 1.0)
        self.assertEqual(report["mrr"], 1.0)

    def test_human_evidence_counts_only_independent_human_questions(self) -> None:
        counts = human_evidence_counts([
            {"question_provenance": "human_task_without_corpus_view"},
            {"question_provenance": "anonymized_real_user_question"},
            {"question_provenance": "synthetic_generated_from_corpus"},
        ])

        self.assertEqual(counts["independent_manual_questions"], 2)
        self.assertEqual(counts["questions_total"], 3)

    def test_campaign_shape_must_match_preregistered_counts(self) -> None:
        cases = [
            {"case_id": "a", "should_abstain": True},
            {"case_id": "b", "should_abstain": False},
            {"case_id": "c", "should_abstain": False},
            {"case_id": "d", "should_abstain": False},
        ]
        assignments = {
            "a": "calibration",
            "b": "calibration",
            "c": "holdout",
            "d": "holdout",
        }
        expected = {
            "expected_cases": 4,
            "expected_abstentions": 1,
            "expected_calibration": 2,
            "expected_holdout": 2,
        }

        counts = validate_campaign_shape(cases, assignments, expected)

        self.assertEqual(counts, {
            "cases": 4,
            "abstentions": 1,
            "calibration": 2,
            "holdout": 2,
        })
        with self.assertRaisesRegex(ValueError, "expected_cases"):
            validate_campaign_shape(cases, assignments, {**expected, "expected_cases": 5})

    def test_gpu_hardware_must_match_manifest_before_workload(self) -> None:
        manifest = {"hardware": {"gpu_model": "NVIDIA A40", "minimum_vram_gib": 40}}
        validated = validate_gpu_hardware("NVIDIA A40", 44 * 1024**3, manifest)
        self.assertEqual(validated["gpu"], "NVIDIA A40")
        with self.assertRaisesRegex(ValueError, "GPU model mismatch"):
            validate_gpu_hardware("NVIDIA GeForce RTX 4090", 24 * 1024**3, manifest)
        with self.assertRaisesRegex(ValueError, "VRAM"):
            validate_gpu_hardware("NVIDIA A40", 32 * 1024**3, manifest)

    def test_gpu_hardware_rejects_non_finite_minimum_vram(self) -> None:
        for minimum in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(minimum=minimum):
                manifest = {
                    "hardware": {
                        "gpu_model": "NVIDIA A40",
                        "minimum_vram_gib": minimum,
                    }
                }
                with self.assertRaisesRegex(ValueError, "finite positive number"):
                    validate_gpu_hardware("NVIDIA A40", 44 * 1024**3, manifest)

    def test_code_revision_must_be_full_lowercase_git_sha(self) -> None:
        sha = "a" * 40
        self.assertEqual(require_code_revision(sha), sha)
        for invalid in (None, "a" * 39, "A" * 40, "not-a-sha"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "40-character lowercase"):
                    require_code_revision(invalid)

    def test_clean_code_revision_must_match_checked_out_head(self) -> None:
        sha = "a" * 40
        self.assertEqual(require_clean_code_revision(sha, sha, ""), sha)
        with self.assertRaisesRegex(ValueError, "does not match checked-out HEAD"):
            require_clean_code_revision(sha, "b" * 40, "")

    def test_clean_code_revision_refuses_dirty_worktree(self) -> None:
        sha = "a" * 40
        with self.assertRaisesRegex(ValueError, "working tree is not clean"):
            require_clean_code_revision(sha, sha, " M scripts/run_bge_gpu_smoke.py\n")

    def test_repository_revision_is_read_from_clean_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "tracked.txt").write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True)
            expected = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True,
                capture_output=True, text=True,
            ).stdout.strip()

            self.assertEqual(read_clean_repository_revision(root), expected)
            (root / "tracked.txt").write_text("dirty\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "working tree is not clean"):
                read_clean_repository_revision(root)

    def test_repository_revision_ignores_inherited_git_repository_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roots = [base / "expected", base / "spoof"]
            revisions = []
            for index, root in enumerate(roots):
                root.mkdir()
                subprocess.run(["git", "init", "-q"], cwd=root, check=True)
                subprocess.run(
                    ["git", "config", "user.email", "test@example.invalid"],
                    cwd=root, check=True,
                )
                subprocess.run(
                    ["git", "config", "user.name", "Test"], cwd=root, check=True
                )
                (root / "tracked.txt").write_text(f"repo-{index}\n", encoding="utf-8")
                subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
                subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True)
                revisions.append(subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=root, check=True,
                    capture_output=True, text=True,
                ).stdout.strip())

            inherited = {
                "GIT_DIR": str(roots[1] / ".git"),
                "GIT_WORK_TREE": str(roots[1]),
            }
            with patch.dict(os.environ, inherited, clear=False):
                observed = read_clean_repository_revision(roots[0])

            self.assertEqual(observed, revisions[0])
            self.assertNotEqual(observed, revisions[1])

    def test_repository_revision_refuses_subdirectory_of_parent_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            nested = root / "nested"
            nested.mkdir()
            (root / "tracked.txt").write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True)

            with self.assertRaisesRegex(ValueError, "repository root"):
                read_clean_repository_revision(nested)

    def test_repository_snapshot_binds_decoding_and_hash_to_same_opened_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            original = b'{"job_id":"original"}\n'
            manifest.write_bytes(original)

            decoded, attestation = read_repository_json_snapshot(root, manifest)
            payload, payload_attestation = read_repository_snapshot(root, manifest)
            manifest.write_text('{"job_id":"replacement"}\n', encoding="utf-8")

            self.assertEqual(decoded, {"job_id": "original"})
            self.assertEqual(attestation["sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(payload, original)
            self.assertEqual(payload_attestation, attestation)

    def test_model_lock_snapshots_bind_execution_data_and_attestation_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            locks = root / "locks"
            locks.mkdir()
            embedding_path = locks / "embedding.json"
            reranker_path = locks / "reranker.json"
            embedding_bytes = b'{"repo_id":"original-embedding","revision":"a"}\n'
            reranker_bytes = b'{"repo_id":"original-reranker","revision":"b"}\n'
            embedding_path.write_bytes(embedding_bytes)
            reranker_path.write_bytes(reranker_bytes)
            manifest = {
                "models": {
                    "embedding_lock": "locks/embedding.json",
                    "reranker_lock": "locks/reranker.json",
                }
            }

            snapshots = read_model_lock_snapshots(root, manifest)
            embedding_path.write_text(
                '{"repo_id":"replacement-embedding","revision":"x"}\n',
                encoding="utf-8",
            )
            reranker_path.write_text(
                '{"repo_id":"replacement-reranker","revision":"y"}\n',
                encoding="utf-8",
            )

            self.assertEqual(snapshots["embedding"]["data"]["repo_id"], "original-embedding")
            self.assertEqual(snapshots["reranker"]["data"]["repo_id"], "original-reranker")
            self.assertEqual(
                snapshots["embedding"]["attestation"],
                {
                    "path": "locks/embedding.json",
                    "sha256": hashlib.sha256(embedding_bytes).hexdigest(),
                },
            )
            self.assertEqual(
                snapshots["reranker"]["attestation"],
                {
                    "path": "locks/reranker.json",
                    "sha256": hashlib.sha256(reranker_bytes).hexdigest(),
                },
            )

    def test_repository_manifest_attestation_binds_regular_in_tree_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifests" / "campaign.json"
            manifest.parent.mkdir()
            manifest.write_text('{"job_id":"test"}\n', encoding="utf-8")

            attestation = repository_file_attestation(root, manifest)

            self.assertEqual(attestation["path"], "manifests/campaign.json")
            self.assertEqual(attestation["sha256"], hashlib.sha256(manifest.read_bytes()).hexdigest())
            self.assertEqual(
                read_attested_json(manifest, attestation["sha256"]),
                {"job_id": "test"},
            )

            manifest.write_text(json.dumps({"job_id": "changed"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                read_attested_json(manifest, attestation["sha256"])

    def test_repository_manifest_attestation_refuses_external_or_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            outside = base / "outside.json"
            outside.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inside the audited repository"):
                repository_file_attestation(root, outside)

            alias = root / "manifest.json"
            alias.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "regular non-symlink"):
                repository_file_attestation(root, alias)

    def test_gpu_report_is_published_atomically_without_temp_residue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory) / "results"
            results.mkdir()
            output = results / "report.json"

            publish_gpu_report_atomic(output, results, {"status": "complete"})

            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                {"status": "complete"},
            )
            self.assertEqual(list(results.glob(".report.json.*.tmp")), [])

    def test_gpu_output_invalidation_removes_stale_report_before_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "data" / "results"
            results.mkdir(parents=True)
            output = results / "human.json"
            output.write_text("STALE", encoding="utf-8")

            invalidate_gpu_output(output, results, protected_paths=[])

            self.assertFalse(output.exists())

    def test_gpu_output_invalidation_refuses_outside_or_input_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "data" / "results"
            results.mkdir(parents=True)
            outside = root / "outside.json"
            outside.write_text("KEEP", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "approved results directory"):
                invalidate_gpu_output(outside, results, protected_paths=[])
            self.assertEqual(outside.read_text(encoding="utf-8"), "KEEP")

            protected = root / "dataset.jsonl"
            protected.write_text("INPUT", encoding="utf-8")
            alias = results / "alias.json"
            alias.symlink_to(protected)
            with self.assertRaisesRegex(ValueError, "aliases a protected input"):
                invalidate_gpu_output(alias, results, protected_paths=[protected])
            self.assertEqual(protected.read_text(encoding="utf-8"), "INPUT")

    def test_reranker_truncation_is_not_claimed_without_boundary_instrumentation(self) -> None:
        evidence = reranker_truncation_evidence(
            rejected_pairs=0,
            maximum_observed_pair_tokens=396,
        )

        self.assertIsNone(evidence["truncated_pairs"])
        self.assertEqual(
            evidence["truncated_pairs_measurement"],
            "not_instrumented_inside_flag_reranker_compute_score",
        )
        self.assertEqual(evidence["rejected_pairs"], 0)
        self.assertEqual(evidence["maximum_observed_pair_tokens"], 396)

    def test_human_execution_metadata_defers_exit_and_command_to_external_receipt(self) -> None:
        metadata = gpu_execution_metadata(
            is_human=True,
            receipt_path="data/results/execution.json",
        )
        self.assertIsNone(metadata["command"])
        self.assertIsNone(metadata["exit_code"])
        self.assertEqual(metadata["external_receipt"], "data/results/execution.json")
        self.assertEqual(metadata["attestation"], "external_launcher_after_process_exit")
        with self.assertRaisesRegex(ValueError, "external execution receipt"):
            gpu_execution_metadata(is_human=True, receipt_path=None)

    def test_legacy_limitations_do_not_claim_a_154_case_human_run(self) -> None:
        limitations = gpu_report_limitations(is_human=False)
        self.assertTrue(any("10 questions" in item for item in limitations))
        self.assertFalse(any("154-case human run" in item for item in limitations))

    def test_human_limitations_identify_calibrated_holdout(self) -> None:
        limitations = gpu_report_limitations(is_human=True)
        self.assertTrue(any("154 reviewed cases" in item for item in limitations))
        self.assertTrue(any("154-case human run" in item for item in limitations))

    def test_human_mapping_refuses_unreviewed_cases(self) -> None:
        with self.assertRaisesRegex(ValueError, "reviewed"):
            human_cases_to_questions(
                [{"reference_status": "pending"}],
                {},
                {"source_revision": "abc", "corpus_manifest_sha": "f" * 64},
            )


if __name__ == "__main__":
    unittest.main()
