from __future__ import annotations

import hashlib
import unittest

from rag_hermes.human_report import run_human_evaluation

PINNED_REVISION = "b682a98ab8cb30c4f0561021e0ff9f41e5156526"
PINNED_SHA = "af0631abbffaab14b180abc4531497665a6104d6685328d6abbe53a565c53866"
DOC_CONTENT = "alpha install Hermes with pipx omega configure the agent safely"


def _documents():
    return {
        "guide": {
            "content": DOC_CONTENT,
            "visibility": "public",
        }
    }


def _manifest():
    return {"source_revision": PINNED_REVISION, "corpus_manifest_sha": PINNED_SHA}


def _case(case_id: str, question: str, language: str, track: str, *, abstain: bool):
    spans = []
    if not abstain:
        passage = "install Hermes with pipx"
        start = DOC_CONTENT.index(passage)
        spans = [
            {
                "document_id": "guide",
                "start_char": start,
                "end_char": start + len(passage),
                "passage_sha256": hashlib.sha256(passage.encode()).hexdigest(),
                "relevance_grade": 2,
            }
        ]
    return {
        "case_id": case_id,
        "question": question,
        "language": language,
        "track": track,
        "category": "no_answer" if abstain else "simple",
        "access_scope": "public",
        "question_provenance": "human_task_without_corpus_view",
        "should_abstain": abstain,
        "unanswerable_reason": "outside_corpus_scope" if abstain else None,
        "reference_status": "validated",
        "source_revision": PINNED_REVISION,
        "corpus_manifest_sha": PINNED_SHA,
        "relevance_spans": spans,
    }


class HumanReportTests(unittest.TestCase):
    def test_reports_overall_tracks_and_categories(self):
        cases = [
            _case("en-answer", "How do I install Hermes?", "en", "en2en", abstain=False),
            _case("fr-answer", "Comment installer Hermes ?", "fr", "fr2en", abstain=False),
            _case("en-none", "What is the lunar constant?", "en", "en2en", abstain=True),
        ]
        report = run_human_evaluation(
            cases,
            _documents(),
            _manifest(),
            k=1,
            minimum_score=0.05,
        )

        self.assertEqual(report["overall"]["cases_total"], 3)
        self.assertEqual(set(report["by_track"]), {"en2en", "fr2en"})
        self.assertEqual(set(report["by_category"]), {"no_answer", "simple"})
        self.assertEqual(report["by_track"]["en2en"]["cases_total"], 2)
        self.assertEqual(
            report["by_track"]["en2en"]["comparison_role"],
            "primary_lexical_baseline",
        )
        self.assertEqual(
            report["by_track"]["fr2en"]["comparison_role"],
            "cross_lingual_diagnostic_only",
        )
        self.assertTrue(report["overall"]["metrics"]["security_gate_passed"])

    def test_rejects_synthetic_case(self):
        case = _case("bad", "How do I install Hermes?", "en", "en2en", abstain=False)
        case["question_provenance"] = "synthetic_generated_from_corpus"
        with self.assertRaisesRegex(ValueError, "quality-eligible"):
            run_human_evaluation([case], _documents(), _manifest(), k=1)

    def test_rejects_pending_reference(self):
        case = _case("bad", "How do I install Hermes?", "en", "en2en", abstain=False)
        case["reference_status"] = "pending"
        with self.assertRaisesRegex(ValueError, "reviewed"):
            run_human_evaluation([case], _documents(), _manifest(), k=1)


if __name__ == "__main__":
    unittest.main()
