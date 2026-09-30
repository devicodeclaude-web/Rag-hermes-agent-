import json
import tempfile
import unittest
from pathlib import Path

from rag_hermes.eval_corpus import corpus_manifest, load_documents

TEST_CORPUS = Path(__file__).parent / "fixtures/eval_corpus.jsonl"


class IngestManualBatchTests(unittest.TestCase):
    """The batch ingester reads a human-filled JSONL template and appends each
    valid case to the v2 dataset, failing closed on any invalid row WITHOUT
    partially writing the batch."""

    def setUp(self):
        import scripts.ingest_manual_batch as ingest
        self.ingest = ingest
        self.docs = load_documents(TEST_CORPUS)
        self.manifest = corpus_manifest(TEST_CORPUS)

        self._tmp_dataset = Path(tempfile.mktemp(suffix=".jsonl"))
        self._tmp_batch = Path(tempfile.mktemp(suffix=".jsonl"))
        self._orig_dataset = ingest.DATASET
        self._orig_corpus = ingest.CORPUS
        ingest.DATASET = self._tmp_dataset
        ingest.CORPUS = TEST_CORPUS

    def tearDown(self):
        self.ingest.DATASET = self._orig_dataset
        self.ingest.CORPUS = self._orig_corpus
        self._tmp_dataset.unlink(missing_ok=True)
        self._tmp_batch.unlink(missing_ok=True)

    def _unique_passage(self):
        import re
        for did, doc in self.docs.items():
            for seg in re.split(r"(?<=[.!?])\s+", doc["content"]):
                seg = seg.strip()
                if 40 < len(seg) < 90 and doc["content"].count(seg) == 1 and "\n" not in seg:
                    return did, seg
        self.fail("no unique passage found in corpus")

    def _write_batch(self, rows):
        self._tmp_batch.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8",
        )

    def test_ingests_a_valid_answerable_row(self):
        did, passage = self._unique_passage()
        self._write_batch([{
            "case_id": "m-001-en", "pair_id": "m-001",
            "question": "How do I do the thing?",
            "language": "en", "track": "en2en", "category": "simple",
            "access_scope": "public",
            "question_provenance": "human_task_without_corpus_view",
            "should_abstain": False, "unanswerable_reason": None,
            "reference_status": "pending",
            "relevant_passages": [
                {"document_id": did, "passage_text": passage, "relevance_grade": 2}
            ],
        }])
        rc = self.ingest.run(self._tmp_batch)
        self.assertEqual(rc, 0)
        lines = [json.loads(l) for l in self._tmp_dataset.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["case_id"], "m-001-en")
        # offsets/hash resolved automatically from the passage text
        self.assertEqual(len(lines[0]["relevance_spans"]), 1)
        self.assertIn("passage_sha256", lines[0]["relevance_spans"][0])

    def test_ingests_an_abstention_row(self):
        self._write_batch([{
            "case_id": "m-002-en",
            "question": "What is the airspeed of an unladen swallow in Hermes?",
            "language": "en", "track": "en2en", "category": "no_answer",
            "access_scope": "public",
            "question_provenance": "human_task_without_corpus_view",
            "should_abstain": True,
            "unanswerable_reason": "outside_corpus_scope",
            "reference_status": "pending",
            "relevant_passages": [],
        }])
        rc = self.ingest.run(self._tmp_batch)
        self.assertEqual(rc, 0)
        lines = [json.loads(l) for l in self._tmp_dataset.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0]["should_abstain"])

    def test_fails_closed_and_writes_nothing_on_an_invalid_row(self):
        did, passage = self._unique_passage()
        self._write_batch([
            {  # valid
                "case_id": "m-010-en", "question": "Q?",
                "language": "en", "track": "en2en", "category": "simple",
                "access_scope": "public",
                "question_provenance": "human_task_without_corpus_view",
                "should_abstain": False, "unanswerable_reason": None,
                "reference_status": "pending",
                "relevant_passages": [
                    {"document_id": did, "passage_text": passage, "relevance_grade": 2}
                ],
            },
            {  # invalid: passage not in the corpus verbatim
                "case_id": "m-011-en", "question": "Q?",
                "language": "en", "track": "en2en", "category": "simple",
                "access_scope": "public",
                "question_provenance": "human_task_without_corpus_view",
                "should_abstain": False, "unanswerable_reason": None,
                "reference_status": "pending",
                "relevant_passages": [
                    {"document_id": did, "passage_text": "ZZZ absent text ZZZ", "relevance_grade": 2}
                ],
            },
        ])
        rc = self.ingest.run(self._tmp_batch)
        self.assertEqual(rc, 1)
        # Atomic: nothing was written because one row was invalid.
        self.assertFalse(self._tmp_dataset.exists() and self._tmp_dataset.read_text().strip())

    def test_rejects_duplicate_case_id_against_existing_dataset(self):
        did, passage = self._unique_passage()
        row = {
            "case_id": "m-020-en", "question": "Q?",
            "language": "en", "track": "en2en", "category": "simple",
            "access_scope": "public",
            "question_provenance": "human_task_without_corpus_view",
            "should_abstain": False, "unanswerable_reason": None,
            "reference_status": "pending",
            "relevant_passages": [
                {"document_id": did, "passage_text": passage, "relevance_grade": 2}
            ],
        }
        self._write_batch([row])
        self.assertEqual(self.ingest.run(self._tmp_batch), 0)
        # Re-ingesting the same case_id must be refused.
        self.assertEqual(self.ingest.run(self._tmp_batch), 1)
        lines = [l for l in self._tmp_dataset.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
