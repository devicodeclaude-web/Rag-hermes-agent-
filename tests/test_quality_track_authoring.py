import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_QA = ROOT / "data/benchmark/dataset-v2.jsonl"
FROZEN_HUMAN = ROOT / "data/benchmark/dataset-v2-human-154.jsonl"
QUALITY_CANDIDATE = ROOT / "data/benchmark/dataset-v2-quality-candidate.jsonl"
FROZEN_CORPUS = ROOT / "data/generated/hermes_public_documents-human-154.jsonl"


class QualityTrackAuthoringTests(unittest.TestCase):
    @staticmethod
    def _pending_abstention(case_id="m-new-en"):
        return {
            "case_id": case_id,
            "question": "What is outside the frozen corpus?",
            "language": "en",
            "track": "en2en",
            "category": "no_answer",
            "access_scope": "public",
            "question_provenance": "human_task_without_corpus_view",
            "should_abstain": True,
            "unanswerable_reason": "outside_corpus_scope",
            "reference_status": "pending",
            "relevant_passages": [],
        }

    def test_authoring_defaults_target_candidate_seeded_from_frozen_human_track(self):
        import scripts.annotate_eval_case as annotate
        import scripts.ingest_manual_batch as ingest
        import scripts.precheck_manual_batch as precheck

        for module in (annotate, ingest, precheck):
            self.assertEqual(module.DATASET, QUALITY_CANDIDATE)
            self.assertNotEqual(module.DATASET, ACTIVE_QA)
            self.assertNotEqual(module.DATASET, FROZEN_HUMAN)
            self.assertEqual(module.CORPUS, FROZEN_CORPUS)

        from rag_hermes.quality_track import verify_quality_candidate_seed

        verify_quality_candidate_seed(QUALITY_CANDIDATE, FROZEN_HUMAN)
        self.assertTrue(
            QUALITY_CANDIDATE.read_bytes().startswith(FROZEN_HUMAN.read_bytes())
        )

    def test_seed_verification_refuses_missing_or_nonprefixed_candidate(self):
        from rag_hermes import quality_track

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / "frozen.jsonl"
            candidate = root / "candidate.jsonl"
            frozen.write_bytes(b'{"case_id":"m-001-en"}\n')

            with self.assertRaisesRegex(ValueError, "missing"):
                quality_track.verify_quality_candidate_seed(candidate, frozen)

            candidate.write_bytes(b'{"case_id":"other"}\n')
            with self.assertRaisesRegex(ValueError, "frozen"):
                quality_track.verify_quality_candidate_seed(candidate, frozen)

            candidate.write_bytes(frozen.read_bytes() + b'{"case_id":"m-002-en"}\n')
            quality_track.verify_quality_candidate_seed(candidate, frozen)

    def test_ingester_refuses_to_create_an_unseeded_candidate(self):
        import scripts.ingest_manual_batch as ingest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / "frozen.jsonl"
            candidate = root / "missing-candidate.jsonl"
            batch = root / "batch.jsonl"
            frozen.write_bytes(b'{"case_id":"m-base-en"}\n')
            batch.write_text(
                json.dumps(self._pending_abstention())
                + "\n",
                encoding="utf-8",
            )
            original_dataset = ingest.DATASET
            original_frozen = getattr(ingest, "FROZEN_BASE", None)
            try:
                ingest.DATASET = candidate
                ingest.FROZEN_BASE = frozen
                self.assertEqual(ingest.run(batch), 1)
                self.assertFalse(candidate.exists())
            finally:
                ingest.DATASET = original_dataset
                if original_frozen is None:
                    del ingest.FROZEN_BASE
                else:
                    ingest.FROZEN_BASE = original_frozen

    def test_single_case_annotator_refuses_an_unseeded_candidate(self):
        import scripts.annotate_eval_case as annotate

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / "frozen.jsonl"
            candidate = root / "missing-candidate.jsonl"
            frozen.write_bytes(b'{"case_id":"m-base-en"}\n')
            original_dataset = annotate.DATASET
            original_frozen = getattr(annotate, "FROZEN_BASE", None)
            try:
                annotate.DATASET = candidate
                annotate.FROZEN_BASE = frozen
                with mock.patch("sys.argv", ["annotate_eval_case.py"]), mock.patch(
                    "sys.stdin", io.StringIO(json.dumps(self._pending_abstention()))
                ), redirect_stderr(io.StringIO()):
                    self.assertEqual(annotate.main(), 2)
                self.assertFalse(candidate.exists())
            finally:
                annotate.DATASET = original_dataset
                if original_frozen is None:
                    del annotate.FROZEN_BASE
                else:
                    annotate.FROZEN_BASE = original_frozen

    def test_precheck_refuses_an_unseeded_candidate(self):
        import scripts.precheck_manual_batch as precheck

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / "frozen.jsonl"
            candidate = root / "missing-candidate.jsonl"
            batch = root / "batch.jsonl"
            frozen.write_bytes(b'{"case_id":"m-base-en"}\n')
            batch.write_text(
                json.dumps(self._pending_abstention()) + "\n", encoding="utf-8"
            )
            original_dataset = precheck.DATASET
            original_frozen = getattr(precheck, "FROZEN_BASE", None)
            try:
                precheck.DATASET = candidate
                precheck.FROZEN_BASE = frozen
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(precheck.run(batch), 2)
                self.assertIn("candidate", output.getvalue().lower())
                self.assertFalse(candidate.exists())
            finally:
                precheck.DATASET = original_dataset
                if original_frozen is None:
                    del precheck.FROZEN_BASE
                else:
                    precheck.FROZEN_BASE = original_frozen

    def test_ingester_adds_jsonl_boundary_after_seed_without_final_newline(self):
        import scripts.ingest_manual_batch as ingest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / "frozen.jsonl"
            candidate = root / "candidate.jsonl"
            batch = root / "batch.jsonl"
            seed = b'{"case_id":"m-base-en"}'
            frozen.write_bytes(seed)
            candidate.write_bytes(seed)
            batch.write_text(
                json.dumps(self._pending_abstention()) + "\n", encoding="utf-8"
            )
            original_dataset = ingest.DATASET
            original_frozen = ingest.FROZEN_BASE
            try:
                ingest.DATASET = candidate
                ingest.FROZEN_BASE = frozen
                self.assertEqual(ingest.run(batch), 0)
            finally:
                ingest.DATASET = original_dataset
                ingest.FROZEN_BASE = original_frozen

            rows = [json.loads(line) for line in candidate.read_text().splitlines()]
            self.assertEqual([row["case_id"] for row in rows], ["m-base-en", "m-new-en"])
            self.assertEqual(frozen.read_bytes(), seed)

    def test_single_annotator_adds_jsonl_boundary_after_seed_without_final_newline(self):
        import scripts.annotate_eval_case as annotate

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / "frozen.jsonl"
            candidate = root / "candidate.jsonl"
            seed = b'{"case_id":"m-base-en"}'
            frozen.write_bytes(seed)
            candidate.write_bytes(seed)
            original_dataset = annotate.DATASET
            original_frozen = annotate.FROZEN_BASE
            try:
                annotate.DATASET = candidate
                annotate.FROZEN_BASE = frozen
                with mock.patch("sys.argv", ["annotate_eval_case.py"]), mock.patch(
                    "sys.stdin", io.StringIO(json.dumps(self._pending_abstention()))
                ), redirect_stdout(io.StringIO()):
                    self.assertEqual(annotate.main(), 0)
            finally:
                annotate.DATASET = original_dataset
                annotate.FROZEN_BASE = original_frozen

            rows = [json.loads(line) for line in candidate.read_text().splitlines()]
            self.assertEqual([row["case_id"] for row in rows], ["m-base-en", "m-new-en"])
            self.assertEqual(frozen.read_bytes(), seed)


if __name__ == "__main__":
    unittest.main()
