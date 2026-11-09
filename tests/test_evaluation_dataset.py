import hashlib
import unittest

from rag_hermes.evaluation_dataset import validate_evaluation_case


PINNED_REVISION = "b682a98ab8cb30c4f0561021e0ff9f41e5156526"
PINNED_SHA = "af0631abbffaab14b180abc4531497665a6104d6685328d6abbe53a565c53866"


class EvaluationDatasetSchemaTests(unittest.TestCase):
    def setUp(self):
        self.documents = {
            "public-doc": {"content": "alpha passage utile omega", "visibility": "public"},
            "private-doc": {"content": "secret passage privé", "visibility": "private"},
        }
        self.manifest = {
            "source_revision": PINNED_REVISION,
            "corpus_manifest_sha": PINNED_SHA,
        }

    def valid_case(self):
        passage = "passage utile"
        return {
            "case_id": "q-001",
            "question": "How do I perform this operation?",
            "language": "en",
            "track": "en2en",
            "category": "simple",
            "access_scope": "public",
            "question_provenance": "human_task_without_corpus_view",
            "should_abstain": False,
            "unanswerable_reason": None,
            "reference_status": "validated",
            "source_revision": PINNED_REVISION,
            "corpus_manifest_sha": PINNED_SHA,
            "relevance_spans": [{
                "document_id": "public-doc",
                "start_char": 6,
                "end_char": 19,
                "passage_sha256": hashlib.sha256(passage.encode()).hexdigest(),
                "relevance_grade": 2,
            }],
        }

    def test_accepts_document_spans_independent_of_chunk_ids(self):
        validated = validate_evaluation_case(self.valid_case(), self.documents, self.manifest)
        self.assertEqual(validated["case_id"], "q-001")
        self.assertNotIn("relevant_chunk_ids", validated)

    def test_rejects_case_id_that_is_not_a_non_empty_string(self):
        for invalid in (None, "", "   ", 7, True, ["q-001"]):
            with self.subTest(invalid=invalid):
                case = self.valid_case()
                case["case_id"] = invalid
                with self.assertRaisesRegex(ValueError, "case_id"):
                    validate_evaluation_case(case, self.documents, self.manifest)

    def test_rejects_category_outside_the_declared_strata(self):
        for invalid in ("nope", "", None, "Simple", 3):
            with self.subTest(invalid=invalid):
                case = self.valid_case()
                case["category"] = invalid
                with self.assertRaisesRegex(ValueError, "category"):
                    validate_evaluation_case(case, self.documents, self.manifest)

    def test_rejects_unhashable_category_with_validation_error(self):
        case = self.valid_case()
        case["category"] = ["simple"]
        with self.assertRaisesRegex(ValueError, "category"):
            validate_evaluation_case(case, self.documents, self.manifest)

    def test_accepts_every_declared_category(self):
        for category in ("simple", "paraphrase", "close_distractor", "chunk_boundary"):
            with self.subTest(category=category):
                case = self.valid_case()
                case["category"] = category
                validated = validate_evaluation_case(case, self.documents, self.manifest)
                self.assertEqual(validated["category"], category)
        # The fifth stratum is abstention-shaped, so it needs its own fixture.
        case = self.valid_case()
        case.update(
            category="no_answer",
            should_abstain=True,
            unanswerable_reason="outside_corpus_scope",
            relevance_spans=[],
        )
        validated = validate_evaluation_case(case, self.documents, self.manifest)
        self.assertEqual(validated["category"], "no_answer")

    def test_rejects_case_id_padded_with_whitespace(self):
        # '  q-001  ' and 'q-001' would otherwise both be accepted as distinct
        # ids, defeating duplicate detection downstream.
        case = self.valid_case()
        case["case_id"] = "  q-001  "
        with self.assertRaisesRegex(ValueError, "case_id"):
            validate_evaluation_case(case, self.documents, self.manifest)

    def test_rejects_no_answer_category_on_an_answerable_case(self):
        case = self.valid_case()
        case["category"] = "no_answer"
        with self.assertRaisesRegex(ValueError, "no_answer"):
            validate_evaluation_case(case, self.documents, self.manifest)

    def test_rejects_abstention_case_filed_under_an_answerable_category(self):
        case = self.valid_case()
        case.update(
            category="simple",
            should_abstain=True,
            unanswerable_reason="outside_corpus_scope",
            relevance_spans=[],
        )
        with self.assertRaisesRegex(ValueError, "no_answer"):
            validate_evaluation_case(case, self.documents, self.manifest)

    def test_validator_vocabulary_matches_the_dataset_qa_gate(self):
        # Drift between the two sets must fail a gate, not a review.
        import importlib.util
        from pathlib import Path

        from rag_hermes.evaluation_dataset import _ALLOWED_CATEGORIES

        gate_path = Path(__file__).resolve().parents[1] / "scripts/check_dataset_qa.py"
        spec = importlib.util.spec_from_file_location("_qa_gate", gate_path)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        self.assertEqual(_ALLOWED_CATEGORIES, gate.ALLOWED_CATEGORIES)

    def test_rejects_chunk_ids_as_primary_labels(self):
        case = self.valid_case()
        case["relevant_chunk_ids"] = ["chunk-new-7"]
        with self.assertRaisesRegex(ValueError, "chunk identifiers"):
            validate_evaluation_case(case, self.documents, self.manifest)

    def test_rejects_span_hash_that_does_not_match_canonical_document(self):
        case = self.valid_case()
        case["relevance_spans"][0]["passage_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "passage_sha256"):
            validate_evaluation_case(case, self.documents, self.manifest)

    def test_no_answer_requires_empty_spans_and_a_reason(self):
        case = self.valid_case()
        case["category"] = "no_answer"
        case["should_abstain"] = True
        case["relevance_spans"] = []
        case["unanswerable_reason"] = "outside_corpus_scope"
        self.assertTrue(
            validate_evaluation_case(case, self.documents, self.manifest)["should_abstain"]
        )

        case["unanswerable_reason"] = None
        with self.assertRaisesRegex(ValueError, "unanswerable_reason"):
            validate_evaluation_case(case, self.documents, self.manifest)

    def test_public_and_private_quality_scopes_cannot_be_silently_mixed(self):
        case = self.valid_case()
        case["access_scope"] = "private"
        with self.assertRaisesRegex(ValueError, "visibility"):
            validate_evaluation_case(case, self.documents, self.manifest)

    def test_language_and_track_are_required(self):
        for field in ("language", "track"):
            case = self.valid_case()
            del case[field]
            with self.assertRaisesRegex(ValueError, "missing fields"):
                validate_evaluation_case(case, self.documents, self.manifest)

    def test_track_language_must_be_consistent(self):
        case = self.valid_case()
        case["track"] = "fr2en"  # requires language fr, but language is en
        with self.assertRaisesRegex(ValueError, "requires language"):
            validate_evaluation_case(case, self.documents, self.manifest)

    def test_accepts_cross_lingual_fr2en_case(self):
        case = self.valid_case()
        case["language"] = "fr"
        case["track"] = "fr2en"
        case["question"] = "Comment effectuer cette opération ?"
        validated = validate_evaluation_case(case, self.documents, self.manifest)
        self.assertEqual(validated["track"], "fr2en")

    def test_rejects_stale_source_revision(self):
        case = self.valid_case()
        case["source_revision"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "source_revision"):
            validate_evaluation_case(case, self.documents, self.manifest)

    def test_rejects_wrong_corpus_manifest_sha(self):
        case = self.valid_case()
        case["corpus_manifest_sha"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "corpus_manifest_sha"):
            validate_evaluation_case(case, self.documents, self.manifest)

    def test_manifest_must_pin_revision_and_sha(self):
        with self.assertRaisesRegex(ValueError, "manifest must pin"):
            validate_evaluation_case(self.valid_case(), self.documents, {})

    def test_accepts_synthetic_provenance_but_marks_it_quality_ineligible(self):
        # A question generated FROM the corpus is honestly recorded as synthetic.
        # It must validate structurally (so the synthetic track can be checked)
        # yet never count as human-grade quality evidence — that separation is
        # what keeps the benchmark non-circular.
        from rag_hermes.evaluation_dataset import (
            SYNTHETIC_PROVENANCE,
            is_quality_eligible,
        )

        case = self.valid_case()
        case["question_provenance"] = SYNTHETIC_PROVENANCE
        validated = validate_evaluation_case(case, self.documents, self.manifest)
        self.assertEqual(validated["question_provenance"], SYNTHETIC_PROVENANCE)
        self.assertFalse(is_quality_eligible(validated))

    def test_human_provenances_are_quality_eligible(self):
        from rag_hermes.evaluation_dataset import is_quality_eligible

        for provenance in (
            "human_task_without_corpus_view",
            "anonymized_real_user_question",
        ):
            case = self.valid_case()
            case["question_provenance"] = provenance
            validated = validate_evaluation_case(case, self.documents, self.manifest)
            self.assertTrue(is_quality_eligible(validated))

    def test_rejects_unknown_provenance(self):
        case = self.valid_case()
        case["question_provenance"] = "scraped_from_somewhere"
        with self.assertRaisesRegex(ValueError, "provenance"):
            validate_evaluation_case(case, self.documents, self.manifest)


if __name__ == "__main__":
    unittest.main()
