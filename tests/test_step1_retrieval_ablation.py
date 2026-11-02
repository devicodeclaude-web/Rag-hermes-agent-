from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rag_hermes.quality_track import FROZEN_HUMAN_CORPUS, FROZEN_HUMAN_DATASET
from scripts import step1_retrieval_ablation as step1


class Step1RetrievalAblationTests(unittest.TestCase):
    def test_three_way_rrf_sums_independent_rank_contributions(self) -> None:
        candidates = list(range(5))
        # BM25 and dense rank 0,1,2,3,4; sparse ranks 0,1,4,2,3.
        descending = [5.0, 4.0, 3.0, 2.0, 1.0]
        sparse = [5.0, 4.0, 2.0, 1.0, 3.0]

        fused = step1._three_way_rrf_indices(
            candidates,
            descending,
            descending,
            sparse,
            limit=5,
            fusion_k=60,
        )

        # A nested two-stage RRF yields 0,1,2,3,4 for this oracle.
        self.assertEqual(fused, [0, 1, 2, 4, 3])

    def test_three_way_rrf_does_not_rank_non_positive_bm25_scores(self) -> None:
        fused = step1._three_way_rrf_indices(
            [0, 1, 2],
            [1.0, 0.0, 0.0],
            [0.0, 3.0, 2.0],
            [0.0, 2.0, 3.0],
            limit=3,
            fusion_k=60,
        )

        self.assertEqual(fused, [0, 1, 2])

    def test_bm25_no_common_term_retrieves_nothing_and_abstains(self) -> None:
        documents = {
            f"doc-{index}": {
                "document_id": f"doc-{index}",
                "content": f"unrelated passage number {index}",
                "tenant_id": "public",
                "visibility": "public",
                "owner_id": "evaluator",
                "allowed_groups": [],
                "allowed_users": [],
                "classification": 0,
                "doc_version": 1,
                "source_uri": f"evaluation://doc-{index}",
            }
            for index in range(5)
        }
        manifest = {"source_revision": "testrev", "corpus_manifest_sha": "f" * 64}
        case = {
            "case_id": "no-overlap",
            "pair_id": "no-overlap",
            "category": "unanswerable",
            "language": "en",
            "track": "en2en",
            "access_scope": "public",
            "question": "zygomorphic xylophone",
            "should_abstain": True,
            "question_provenance": "human_task_without_corpus_view",
            "reference_status": "validated",
            "source_revision": "testrev",
            "corpus_manifest_sha": "f" * 64,
            "unanswerable_reason": "outside_corpus_scope",
            "relevance_spans": [],
        }

        result = step1.run_ablation(
            [case],
            documents,
            manifest,
            embedder=step1.FakeEmbedder(),
            reranker=step1.FakeReranker(),
            tokenizer=step1.FakeTokenizer(),
        )

        bm25 = result["modes"]["bm25"]["overall"]["metrics"]
        self.assertEqual(bm25["abstention_precision"], 1.0)
        self.assertEqual(bm25["abstention_recall"], 1.0)
        self.assertEqual(bm25["citation_precision"], 0.0)

    def test_git_state_uses_sha40_and_neutralizes_git_environment(self) -> None:
        completed = [
            subprocess.CompletedProcess([], 0, stdout="a" * 40 + "\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="?? local-change\n", stderr=""),
        ]
        with (
            mock.patch.dict(step1.os.environ, {"GIT_DIR": "/hostile", "GIT_WORK_TREE": "/wrong"}),
            mock.patch("subprocess.run", side_effect=completed) as run,
        ):
            state = getattr(step1, "_git_state", lambda: {})()

        self.assertEqual(state, {"audited_commit": "a" * 40, "working_tree_dirty": True})
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["cwd"], step1.ROOT)
            self.assertFalse(any(key.startswith("GIT_") for key in call.kwargs["env"]))

    def test_output_validation_requires_154_records_with_five_contexts(self) -> None:
        payload = {
            "audited_commit": "a" * 40,
            "timestamp_utc": "2026-11-01T12:00:00Z",
            "command": ["runner", "--fake-models"],
            "exit_code": 0,
            "python_version": "3.test",
            "qdrant": "not_exercised",
            "models": {
                name: {"name": f"fake_{name}", "revision": "test-revision"}
                for name in ("embedder", "reranker", "tokenizer")
            },
            "deterministic_seed": 20260923,
            "protocol": {"path": "/protocol.md", "sha256": "b" * 64},
            "inputs": {"dataset_sha256": "c" * 64, "cases": 154},
            "working_tree_dirty": True,
            "protocol_decision_eligible": False,
            "fake_models_required": True,
            "quality_evidence": False,
            "acl": {"scope": "public_only_mechanism_check"},
            "results": {
                "reranked_contexts": [
                    {"case_id": f"case-{index}", "contexts": [{}] * 5}
                    for index in range(153)
                ]
            },
        }
        validate = getattr(step1, "_validate_payload", lambda _payload: None)

        with self.assertRaisesRegex(ValueError, "exactly 154 case records"):
            validate(payload)

        payload["results"]["reranked_contexts"].append(
            {"case_id": "case-153", "contexts": [{}] * 4}
        )
        with self.assertRaisesRegex(ValueError, "exactly five contexts"):
            validate(payload)

    def test_fsync_directory_opens_syncs_and_closes_directory_fd(self) -> None:
        directory = Path("/tmp/output-parent")
        with (
            mock.patch.object(step1.os, "open", return_value=987) as open_fd,
            mock.patch.object(step1.os, "fsync") as fsync,
            mock.patch.object(step1.os, "close") as close,
        ):
            getattr(step1, "_fsync_directory", lambda _path: None)(directory)

        open_fd.assert_called_once_with(directory, step1.os.O_RDONLY | step1.os.O_DIRECTORY)
        fsync.assert_called_once_with(987)
        close.assert_called_once_with(987)

    def test_atomic_write_fsyncs_parent_after_replace(self) -> None:
        events = []
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "report.json"
            real_replace = step1.os.replace

            def replace(source, destination):
                real_replace(source, destination)
                events.append("replace")

            with (
                mock.patch.object(step1.os, "replace", side_effect=replace),
                mock.patch.object(
                    step1,
                    "_fsync_directory",
                    side_effect=lambda path: events.append(("fsync", path)),
                ),
            ):
                step1._atomic_write_json(output, {"ok": True})

        self.assertEqual(events, ["replace", ("fsync", output.parent)])

    def test_cli_is_pinned_to_frozen_inputs_and_requires_fake_models(self) -> None:
        parser = step1._build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args([])
        args = parser.parse_args(["--fake-models"])

        self.assertEqual(args.dataset, FROZEN_HUMAN_DATASET)
        self.assertEqual(args.corpus, FROZEN_HUMAN_CORPUS)
        self.assertTrue(args.fake_models)
        self.assertIsInstance(args.results, Path)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--fake-models", "--k", "1"])

    def test_direct_script_help_imports_project(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(Path(step1.__file__)), "--help"],
            cwd=Path(step1.__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--fake-models", completed.stdout)

    def test_fake_runner_exercises_six_modes_with_official_span_metrics(self) -> None:
        content = "alpha install Hermes safely omega"
        documents = {
            "guide": {
                "document_id": "guide",
                "content": content,
                "tenant_id": "public",
                "visibility": "public",
                "owner_id": "evaluator",
                "allowed_groups": [],
                "allowed_users": [],
                "classification": 0,
                "doc_version": 1,
                "source_uri": "evaluation://guide",
            },
            **{
                f"distractor-{index}": {
                    "document_id": f"distractor-{index}",
                    "content": f"unrelated public distractor {index}",
                    "tenant_id": "public",
                    "visibility": "public",
                    "owner_id": "evaluator",
                    "allowed_groups": [],
                    "allowed_users": [],
                    "classification": 0,
                    "doc_version": 1,
                    "source_uri": f"evaluation://distractor-{index}",
                }
                for index in range(4)
            },
        }
        passage = "install Hermes safely"
        start = content.index(passage)
        manifest = {"source_revision": "testrev", "corpus_manifest_sha": "f" * 64}
        base = {
            "pair_id": "pair-1",
            "category": "simple",
            "access_scope": "public",
            "question_provenance": "human_task_without_corpus_view",
            "reference_status": "validated",
            "source_revision": "testrev",
            "corpus_manifest_sha": "f" * 64,
            "unanswerable_reason": None,
            "relevance_spans": [{
                "document_id": "guide",
                "start_char": start,
                "end_char": start + len(passage),
                "passage_sha256": hashlib.sha256(passage.encode()).hexdigest(),
                "relevance_grade": 2,
            }],
        }
        cases = [
            {**base, "case_id": "pair-1-en", "language": "en", "track": "en2en", "question": "How install Hermes safely?", "should_abstain": False},
            {**base, "case_id": "pair-1-fr", "language": "fr", "track": "fr2en", "question": "Comment installer Hermes?", "should_abstain": False},
        ]

        result = step1.run_ablation(
            cases,
            documents,
            manifest,
            embedder=step1.FakeEmbedder(),
            reranker=step1.FakeReranker(),
            tokenizer=step1.FakeTokenizer(),
            k=5,
        )

        self.assertEqual(set(result["modes"]), set(step1.MODES))
        for mode in step1.MODES:
            self.assertEqual(result["modes"][mode]["overall"]["metrics"]["case_count"], 2)
            self.assertEqual(set(result["modes"][mode]["by_track"]), {"en2en", "fr2en"})
            self.assertEqual(result["modes"][mode]["overall"]["metrics"]["leak_count"], 0)
        self.assertEqual(len(result["reranked_contexts"]), 2)
        self.assertTrue(all(
            len(record["contexts"]) == 5
            for record in result["reranked_contexts"]
        ))
        self.assertEqual(result["budget"]["policy"], "reject_never_truncate")
        self.assertEqual(result["budget"]["truncated_pairs"], 0)
        self.assertTrue(result["abstention_threshold_sweep"])

    def test_budget_counts_each_pair_once_skips_rejected_and_fills_five(self) -> None:
        query = " ".join(["query"] * 215)
        documents = {}
        for index in range(6):
            content = " ".join(["query"] * (300 if index == 0 else 2))
            documents[f"doc-{index}"] = {
                "document_id": f"doc-{index}", "content": content,
                "tenant_id": "public", "visibility": "public", "owner_id": "evaluator",
                "allowed_groups": [], "allowed_users": [], "classification": 0,
                "doc_version": 1, "source_uri": f"evaluation://doc-{index}",
            }
        manifest = {"source_revision": "testrev", "corpus_manifest_sha": "f" * 64}
        passage = documents["doc-1"]["content"]
        case = {
            "case_id": "budget-case", "pair_id": "budget-pair", "category": "simple",
            "language": "en", "track": "en2en", "access_scope": "public",
            "question": query, "should_abstain": False,
            "question_provenance": "human_task_without_corpus_view",
            "reference_status": "validated", "source_revision": "testrev",
            "corpus_manifest_sha": "f" * 64, "unanswerable_reason": None,
            "relevance_spans": [{
                "document_id": "doc-1", "start_char": 0, "end_char": len(passage),
                "passage_sha256": hashlib.sha256(passage.encode()).hexdigest(),
                "relevance_grade": 2,
            }],
        }

        class CountingTokenizer(step1.FakeTokenizer):
            def __init__(self) -> None:
                self.pair_calls = 0

            def __call__(self, text, text_pair=None, **kwargs):
                if text_pair is not None:
                    self.pair_calls += 1
                return super().__call__(text, text_pair, **kwargs)

        class RecordingReranker(step1.FakeReranker):
            def __init__(self) -> None:
                self.passages = []

            def compute_score(self, pairs, **kwargs):
                self.passages.extend(pair[1] for pair in pairs)
                return super().compute_score(pairs, **kwargs)

        tokenizer = CountingTokenizer()
        reranker = RecordingReranker()
        result = step1.run_ablation(
            [case], documents, manifest,
            embedder=step1.FakeEmbedder(), reranker=reranker, tokenizer=tokenizer,
        )

        self.assertEqual(len(result["reranked_contexts"][0]["contexts"]), 5)
        self.assertEqual(result["budget"]["checked_pairs"], 6)
        self.assertEqual(result["budget"]["rejected_pairs"], 1)
        self.assertGreater(result["budget"]["maximum_observed_pair_tokens"], 512)
        self.assertEqual(tokenizer.pair_calls, 6)
        self.assertEqual(len(reranker.passages), 5)
        self.assertNotIn(documents["doc-0"]["content"], reranker.passages)

    def test_frozen_input_attestation_rejects_alternate_paths(self) -> None:
        attestation = step1.attest_frozen_inputs(
            FROZEN_HUMAN_DATASET, FROZEN_HUMAN_CORPUS
        )

        self.assertEqual(attestation["cases"], 154)
        self.assertEqual(attestation["corpus_documents"], 461)
        self.assertEqual(len(attestation["dataset_sha256"]), 64)
        self.assertEqual(len(attestation["corpus_sha256"]), 64)
        with tempfile.TemporaryDirectory() as raw:
            copied = Path(raw) / "dataset.jsonl"
            copied.write_bytes(FROZEN_HUMAN_DATASET.read_bytes())
            with self.assertRaisesRegex(ValueError, "frozen snapshot path"):
                step1.attest_frozen_inputs(copied, FROZEN_HUMAN_CORPUS)

    def test_failed_run_removes_stale_result_after_alias_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "step1.json"
            output.write_text("STALE-SUCCESS", encoding="utf-8")
            with (
                mock.patch.object(step1.sys, "argv", [
                    "step1_retrieval_ablation.py", "--fake-models", "--results", str(output)
                ]),
                mock.patch.object(step1, "attest_frozen_inputs", side_effect=ValueError("invalid dataset")),
            ):
                exit_code = step1.main()

            self.assertEqual(exit_code, 1)
            self.assertFalse(output.exists())

    def test_argument_error_removes_stale_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "step1.json"
            output.write_text("STALE-SUCCESS", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(step1.__file__)),
                    "--fake-models",
                    "--results",
                    str(output),
                    "--k",
                    "1",
                ],
                cwd=Path(step1.__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                timeout=30,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(output.exists())

    def test_result_aliases_to_noncanonical_cli_inputs_are_preserved(self) -> None:
        for input_option in ("--dataset", "--corpus"):
            for alias_kind in ("direct", "symlink", "hardlink"):
                with self.subTest(input_option=input_option, alias_kind=alias_kind):
                    with tempfile.TemporaryDirectory() as raw:
                        directory = Path(raw)
                        source = directory / "input.jsonl"
                        source.write_bytes(b"INPUT-SENTINEL\n")
                        output = directory / "result.json"
                        if alias_kind == "direct":
                            output = source
                        elif alias_kind == "symlink":
                            output.symlink_to(source)
                        else:
                            subprocess.run(
                                ["ln", str(source), str(output)], check=True
                            )

                        completed = subprocess.run(
                            [
                                sys.executable,
                                str(Path(step1.__file__)),
                                "--fake-models",
                                input_option,
                                str(source),
                                "--results",
                                str(output),
                            ],
                            cwd=Path(step1.__file__).resolve().parents[1],
                            text=True,
                            capture_output=True,
                            timeout=30,
                        )

                        self.assertNotEqual(completed.returncode, 0)
                        self.assertTrue(source.exists())
                        self.assertEqual(source.read_bytes(), b"INPUT-SENTINEL\n")
                        self.assertTrue(output.exists() or output.is_symlink())

    def test_directory_fsync_failure_leaves_no_consumable_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "step1.json"
            with mock.patch.object(
                step1, "_fsync_directory", side_effect=OSError("fsync failed")
            ):
                with self.assertRaisesRegex(OSError, "fsync failed"):
                    step1._atomic_write_json(output, {"ok": True})

            self.assertFalse(output.exists())

    def test_cli_atomically_reports_real_frozen_run_as_fake_mechanism_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "step1.json"
            command = [
                "step1_retrieval_ablation.py", "--fake-models", "--results", str(output)
            ]
            with (
                mock.patch.object(step1.sys, "argv", command),
                mock.patch.object(step1, "_git_state", return_value={
                    "audited_commit": "a" * 40,
                    "working_tree_dirty": True,
                }),
            ):
                exit_code = step1.main()

            self.assertEqual(exit_code, 0)
            payload = step1.json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["evidence_classification"],
                "fake_models_mechanism_only_not_quality_evidence",
            )
            self.assertFalse(payload["quality_evidence"])
            self.assertEqual(payload["audited_commit"], "a" * 40)
            self.assertRegex(payload["timestamp_utc"], r"^\d{4}-\d{2}-\d{2}T.*Z$")
            self.assertEqual(payload["command"], command)
            self.assertEqual(payload["exit_code"], 0)
            self.assertEqual(payload["python_version"], sys.version)
            self.assertEqual(payload["qdrant"], "not_exercised")
            self.assertEqual(payload["deterministic_seed"], 20260923)
            self.assertEqual(payload["protocol"]["path"], str((step1.ROOT / "docs/ablation-protocol.md").resolve()))
            self.assertEqual(
                payload["protocol"]["sha256"],
                hashlib.sha256((step1.ROOT / "docs/ablation-protocol.md").read_bytes()).hexdigest(),
            )
            self.assertTrue(payload["working_tree_dirty"])
            self.assertFalse(payload["protocol_decision_eligible"])
            self.assertEqual(
                payload["protocol_decision_ineligibility_reasons"],
                ["fake_models", "working_tree_dirty"],
            )
            self.assertEqual(payload["acl"]["scope"], "public_only_mechanism_check")
            for model in ("embedder", "reranker", "tokenizer"):
                self.assertEqual(set(payload["models"][model]), {"name", "revision"})
                self.assertTrue(payload["models"][model]["name"].startswith("fake_"))
                self.assertTrue(payload["models"][model]["revision"])
            self.assertEqual(payload["inputs"]["cases"], 154)
            self.assertEqual(payload["inputs"]["corpus_documents"], 461)
            self.assertEqual(len(payload["results"]["reranked_contexts"]), 154)
            self.assertTrue(all(
                len(record["contexts"]) == 5
                for record in payload["results"]["reranked_contexts"]
            ))
            self.assertTrue(all(
                mode["overall"]["metrics"]["leak_count"] == 0
                for mode in payload["results"]["modes"].values()
            ))
            self.assertFalse(list(output.parent.glob(".step1.json.*.tmp")))


if __name__ == "__main__":
    unittest.main()
