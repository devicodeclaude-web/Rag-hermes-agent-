import json
import tempfile
import unittest
from pathlib import Path

from rag_hermes.eval_corpus import corpus_manifest, find_passage_span, load_documents

TEST_CORPUS = Path(__file__).parent / "fixtures/eval_corpus.jsonl"


class EvalCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = load_documents(TEST_CORPUS)
        cls.manifest = corpus_manifest(TEST_CORPUS)

    def test_manifest_pins_single_revision_and_content_hash(self):
        self.assertRegex(self.manifest["source_revision"], r"^[0-9a-f]{7,40}$")
        self.assertRegex(self.manifest["corpus_manifest_sha"], r"^[0-9a-f]{64}$")

    def test_find_passage_span_is_verbatim_and_hashed(self):
        did = next(iter(self.docs))
        content = self.docs[did]["content"]
        passage = content[50:110]
        span = find_passage_span(self.docs, did, passage)
        self.assertEqual(span["start_char"], 50)
        self.assertEqual(span["end_char"], 110)
        self.assertEqual(content[span["start_char"]:span["end_char"]], passage)

    def test_find_passage_span_rejects_absent_text(self):
        did = next(iter(self.docs))
        with self.assertRaisesRegex(ValueError, "not found verbatim"):
            find_passage_span(self.docs, did, "this exact string is not in the corpus zzzq")

    def test_find_passage_span_rejects_ambiguous_text(self):
        # A single space almost certainly appears more than once.
        did = next(iter(self.docs))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            find_passage_span(self.docs, did, " ")


class AnnotateAndValidateChainTests(unittest.TestCase):
    """End-to-end: annotate an EN case + its FR pair, then validate the dataset."""

    def setUp(self):
        import scripts.annotate_eval_case as annotate
        import scripts.validate_dataset_v2 as validate
        self.annotate = annotate
        self.validate = validate
        self._tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        self._tmp.close()
        self.path = Path(self._tmp.name)
        self.path.unlink(missing_ok=True)
        self._orig_a = annotate.DATASET
        self._orig_v = validate.DATASET
        self._orig_corpus = validate.CORPUS
        self._orig_en = validate.TARGET_EN
        self._orig_fr = validate.TARGET_FR_PAIRS
        self._orig_abstention_rate = validate.TARGET_MIN_ABSTENTION_RATE
        annotate.DATASET = self.path
        validate.DATASET = self.path
        validate.CORPUS = TEST_CORPUS
        validate.TARGET_EN = 1
        validate.TARGET_FR_PAIRS = 1
        # This chain test covers annotation + pair validation, not dataset mix.
        validate.TARGET_MIN_ABSTENTION_RATE = 0.0

    def tearDown(self):
        self.annotate.DATASET = self._orig_a
        self.validate.DATASET = self._orig_v
        self.validate.CORPUS = self._orig_corpus
        self.validate.TARGET_EN = self._orig_en
        self.validate.TARGET_FR_PAIRS = self._orig_fr
        self.validate.TARGET_MIN_ABSTENTION_RATE = self._orig_abstention_rate
        self.path.unlink(missing_ok=True)

    def _passage(self):
        import re
        docs = load_documents(TEST_CORPUS)
        for did, doc in docs.items():
            for seg in re.split(r"(?<=[.!?])\s+", doc["content"]):
                seg = seg.strip()
                if 40 < len(seg) < 90 and doc["content"].count(seg) == 1 and "\n" not in seg:
                    return did, seg
        self.fail("no unique passage found in corpus")

    def test_pair_annotation_validates_ready(self):
        did, passage = self._passage()
        docs = load_documents(TEST_CORPUS)
        manifest = corpus_manifest(TEST_CORPUS)
        base = {
            "case_id": "t-001-en", "pair_id": "t-001",
            "question": "How does this work?", "language": "en", "track": "en2en",
            "category": "simple", "access_scope": "public",
            "question_provenance": "human_task_without_corpus_view",
            "should_abstain": False, "unanswerable_reason": None,
            "reference_status": "validated",
            "relevant_passages": [{"document_id": did, "passage_text": passage, "relevance_grade": 2}],
        }
        fr = {**base, "case_id": "t-001-fr", "language": "fr", "track": "fr2en",
              "question": "Comment cela fonctionne-t-il ?"}
        for raw in (base, fr):
            self.annotate.atomic_append(self.annotate.build_case(raw, docs, manifest))

        import sys
        old_argv = sys.argv
        sys.argv = ["validate"]
        try:
            rc = self.validate.main()
        finally:
            sys.argv = old_argv
        self.assertEqual(rc, 0)
        lines = [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main()
