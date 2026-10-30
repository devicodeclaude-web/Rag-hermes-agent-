from __future__ import annotations

import unittest

from rag_hermes.review_aggregate import (
    ReviewAggregate,
    aggregate_review,
)


def _pair(case_id, *, should_abstain, rag_correct, cb_correct, notes=""):
    return {
        "case_id": case_id,
        "question": f"q-{case_id}",
        "should_abstain": should_abstain,
        "rag_answer": "rag",
        "closed_book_answer": "cb",
        "human_verdict": {
            "rag_correct": rag_correct,
            "closed_book_correct": cb_correct,
            "notes": notes,
        },
    }


class AggregateReviewTests(unittest.TestCase):
    def test_computes_accuracy_for_both_campaigns(self):
        pairs = [
            _pair("c1", should_abstain=False, rag_correct=True, cb_correct=False),
            _pair("c2", should_abstain=False, rag_correct=True, cb_correct=True),
            _pair("c3", should_abstain=False, rag_correct=False, cb_correct=False),
            _pair("c4", should_abstain=True, rag_correct=True, cb_correct=True),
        ]
        report = aggregate_review(pairs)
        self.assertIsInstance(report, ReviewAggregate)
        self.assertEqual(report.reviewed, 4)
        self.assertEqual(report.total, 4)
        # RAG correct on c1,c2,c4 => 3/4 ; closed-book on c2,c4 => 2/4
        self.assertAlmostEqual(report.rag_accuracy, 0.75)
        self.assertAlmostEqual(report.closed_book_accuracy, 0.5)
        # RAG strictly better than closed-book on c1 ; never worse here
        self.assertEqual(report.rag_better_count, 1)
        self.assertEqual(report.closed_book_better_count, 0)

    def test_fails_closed_when_any_verdict_is_unreviewed(self):
        pairs = [
            _pair("c1", should_abstain=False, rag_correct=True, cb_correct=False),
            _pair("c2", should_abstain=False, rag_correct=None, cb_correct=None),
        ]
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            aggregate_review(pairs)

    def test_partial_review_allowed_when_explicitly_requested(self):
        pairs = [
            _pair("c1", should_abstain=False, rag_correct=True, cb_correct=False),
            _pair("c2", should_abstain=False, rag_correct=None, cb_correct=None),
        ]
        report = aggregate_review(pairs, require_complete=False)
        self.assertEqual(report.total, 2)
        self.assertEqual(report.reviewed, 1)
        # Accuracy denominators use only reviewed cases.
        self.assertAlmostEqual(report.rag_accuracy, 1.0)   # 1/1 reviewed
        self.assertAlmostEqual(report.closed_book_accuracy, 0.0)

    def test_rejects_non_bool_verdict(self):
        pairs = [_pair("c1", should_abstain=False, rag_correct="yes", cb_correct=False)]
        with self.assertRaises(ValueError):
            aggregate_review(pairs, require_complete=False)

    def test_rejects_duplicate_case_id(self):
        pairs = [
            _pair("dup", should_abstain=False, rag_correct=True, cb_correct=True),
            _pair("dup", should_abstain=True, rag_correct=True, cb_correct=True),
        ]
        with self.assertRaises(ValueError):
            aggregate_review(pairs)

    def test_rejects_missing_human_verdict_block(self):
        pair = {
            "case_id": "c1",
            "question": "q",
            "should_abstain": False,
            "rag_answer": "r",
            "closed_book_answer": "c",
        }
        with self.assertRaises(ValueError):
            aggregate_review([pair])

    def test_empty_sample_is_rejected(self):
        with self.assertRaises(ValueError):
            aggregate_review([])


if __name__ == "__main__":
    unittest.main()
