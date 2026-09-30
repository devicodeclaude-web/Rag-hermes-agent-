import hashlib
import unittest

from rag_hermes.evaluation_dataset import (
    SYNTHETIC_PROVENANCE,
    is_quality_eligible,
    validate_evaluation_case,
)
from rag_hermes.synthetic_dataset import build_synthetic_case

PINNED_REVISION = "b682a98ab8cb30c4f0561021e0ff9f41e5156526"
PINNED_SHA = "af0631abbffaab14b180abc4531497665a6104d6685328d6abbe53a565c53866"


class BuildSyntheticCaseTests(unittest.TestCase):
    def setUp(self):
        self.documents = {
            "doc-a": {"content": "alpha canonical passage omega", "visibility": "public"},
            "doc-b": {"content": "beta distractor material here", "visibility": "public"},
        }
        self.manifest = {
            "source_revision": PINNED_REVISION,
            "corpus_manifest_sha": PINNED_SHA,
        }

    def test_answerable_case_becomes_full_document_span_synthetic(self):
        raw = {
            "case_id": "v1-001",
            "category": "simple",
            "question": "What does doc-a explain?",
            "relevant_document_ids": ["doc-a"],
            "distractor_document_ids": ["doc-b"],
        }
        case = build_synthetic_case(raw, self.documents, self.manifest)

        # Honest synthetic provenance, never quality-eligible.
        self.assertEqual(case["question_provenance"], SYNTHETIC_PROVENANCE)
        self.assertFalse(is_quality_eligible(case))
        self.assertEqual(case["reference_status"], "pending")
        self.assertEqual(case["track"], "en2en")
        self.assertEqual(case["language"], "en")
        self.assertEqual(case["access_scope"], "public")
        self.assertFalse(case["should_abstain"])
        self.assertIsNone(case["unanswerable_reason"])

        # Full-document span: start=0, end=len(content), hash matches.
        self.assertEqual(len(case["relevance_spans"]), 1)
        span = case["relevance_spans"][0]
        content = self.documents["doc-a"]["content"]
        self.assertEqual(span["document_id"], "doc-a")
        self.assertEqual(span["start_char"], 0)
        self.assertEqual(span["end_char"], len(content))
        self.assertEqual(
            span["passage_sha256"],
            hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(span["relevance_grade"], 2)

        # It must pass the canonical strict validator with the pinned manifest.
        validate_evaluation_case(case, self.documents, self.manifest)

    def test_no_answer_case_becomes_abstention_with_reason(self):
        raw = {
            "case_id": "v1-081",
            "category": "no_answer",
            "question": "What lunar constant does the portal doc prescribe?",
            "relevant_document_ids": [],
            "distractor_document_ids": ["doc-b"],
        }
        case = build_synthetic_case(raw, self.documents, self.manifest)

        self.assertTrue(case["should_abstain"])
        self.assertEqual(case["relevance_spans"], [])
        self.assertTrue(case["unanswerable_reason"])  # non-empty
        self.assertEqual(case["question_provenance"], SYNTHETIC_PROVENANCE)
        validate_evaluation_case(case, self.documents, self.manifest)

    def test_category_is_preserved_for_traceability(self):
        raw = {
            "case_id": "v1-030",
            "category": "close_distractor",
            "question": "Q?",
            "relevant_document_ids": ["doc-a"],
            "distractor_document_ids": [],
        }
        case = build_synthetic_case(raw, self.documents, self.manifest)
        self.assertEqual(case["category"], "close_distractor")

    def test_unknown_relevant_document_is_rejected(self):
        raw = {
            "case_id": "v1-999",
            "category": "simple",
            "question": "Q?",
            "relevant_document_ids": ["does-not-exist"],
            "distractor_document_ids": [],
        }
        with self.assertRaises((KeyError, ValueError)):
            build_synthetic_case(raw, self.documents, self.manifest)

    def test_answerable_case_without_relevant_docs_is_rejected(self):
        # A non-abstention category must carry at least one relevant document.
        raw = {
            "case_id": "v1-777",
            "category": "simple",
            "question": "Q?",
            "relevant_document_ids": [],
            "distractor_document_ids": [],
        }
        with self.assertRaises(ValueError):
            build_synthetic_case(raw, self.documents, self.manifest)


if __name__ == "__main__":
    unittest.main()
