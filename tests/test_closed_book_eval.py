from __future__ import annotations

import unittest

from rag_hermes.closed_book import CLOSED_BOOK_ABSTENTION
from rag_hermes.closed_book_eval import (
    ClosedBookReport,
    run_closed_book_evaluation,
)


def _case(case_id, question, should_abstain):
    return {"case_id": case_id, "question": question, "should_abstain": should_abstain}


class ClosedBookEvaluationTests(unittest.TestCase):
    def test_scores_abstention_precision_and_recall(self):
        # 4 cases: 2 should abstain, 2 should answer.
        cases = [
            _case("a1", "unknowable 1", True),
            _case("a2", "unknowable 2", True),
            _case("b1", "answerable 1", False),
            _case("b2", "answerable 2", False),
        ]

        # Generator: abstains on a1 (correct) and b1 (wrong), answers otherwise.
        def generator(question):
            if question in ("unknowable 1", "answerable 1"):
                return CLOSED_BOOK_ABSTENTION
            return "some concrete answer"

        report = run_closed_book_evaluation(cases, generator)
        self.assertIsInstance(report, ClosedBookReport)
        self.assertEqual(report.total, 4)
        self.assertEqual(report.predicted_abstentions, 2)  # a1, b1
        self.assertEqual(report.required_abstentions, 2)   # a1, a2
        self.assertEqual(report.true_positive_abstentions, 1)  # only a1
        self.assertAlmostEqual(report.abstention_precision, 0.5)  # 1/2
        self.assertAlmostEqual(report.abstention_recall, 0.5)     # 1/2
        # answered_case_ids exposes which answerable cases got a concrete answer
        # so a human review sample can be drawn from them.
        self.assertIn("b2", report.answered_case_ids)
        self.assertNotIn("b1", report.answered_case_ids)  # b1 abstained

    def test_all_correct_abstention(self):
        cases = [_case("a1", "q-abstain", True), _case("b1", "q-answer", False)]

        def generator(question):
            return CLOSED_BOOK_ABSTENTION if question == "q-abstain" else "answer"

        report = run_closed_book_evaluation(cases, generator)
        self.assertEqual(report.abstention_precision, 1.0)
        self.assertEqual(report.abstention_recall, 1.0)

    def test_rejects_should_abstain_not_bool(self):
        cases = [{"case_id": "x", "question": "q", "should_abstain": "yes"}]
        with self.assertRaises(ValueError):
            run_closed_book_evaluation(cases, lambda q: "a")

    def test_rejects_duplicate_case_id(self):
        cases = [_case("dup", "q1", False), _case("dup", "q2", True)]
        with self.assertRaises(ValueError):
            run_closed_book_evaluation(cases, lambda q: "a")

    def test_records_generation_failure_without_crashing(self):
        from rag_hermes.closed_book import GenerationError

        cases = [_case("a1", "boom", False)]

        def generator(question):
            raise GenerationError("provider down")

        report = run_closed_book_evaluation(cases, generator)
        # A generation failure is neither an answer nor an abstention.
        self.assertEqual(report.generation_failures, 1)
        self.assertEqual(report.predicted_abstentions, 0)
        self.assertNotIn("a1", report.answered_case_ids)


if __name__ == "__main__":
    unittest.main()
