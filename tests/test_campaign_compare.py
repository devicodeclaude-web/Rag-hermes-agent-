from __future__ import annotations

import unittest

from rag_hermes.campaign_compare import (
    ComparisonPair,
    build_review_sample,
    compare_campaigns,
)
from rag_hermes.closed_book import CLOSED_BOOK_ABSTENTION
from rag_hermes.generator import ABSTENTION_ANSWER as RAG_ABSTENTION


def _case(case_id, question, should_abstain):
    return {"case_id": case_id, "question": question, "should_abstain": should_abstain}


class BuildReviewSampleTests(unittest.TestCase):
    def test_pairs_rag_and_closed_book_answers_per_case(self):
        cases = [
            _case("q1", "How to install?", False),
            _case("q2", "Unknowable?", True),
        ]

        def rag_answer(question):
            return "RAG: use pipx [S1]" if "install" in question else CLOSED_BOOK_ABSTENTION

        def closed_book_answer(question):
            return "CB: use apt" if "install" in question else CLOSED_BOOK_ABSTENTION

        pairs = build_review_sample(
            cases, rag_answer, closed_book_answer, fraction=1.0, seed=1
        )
        self.assertEqual(len(pairs), 2)
        self.assertTrue(all(isinstance(p, ComparisonPair) for p in pairs))
        by_id = {p.case_id: p for p in pairs}
        self.assertEqual(by_id["q1"].rag_answer, "RAG: use pipx [S1]")
        self.assertEqual(by_id["q1"].closed_book_answer, "CB: use apt")
        self.assertFalse(by_id["q1"].should_abstain)
        self.assertTrue(by_id["q2"].should_abstain)

    def test_sample_fraction_is_at_least_twenty_percent_and_deterministic(self):
        cases = [_case(f"q{i}", f"question {i}", i % 5 == 0) for i in range(10)]
        ans = lambda q: "answer for " + q

        sample_a = build_review_sample(cases, ans, ans, fraction=0.2, seed=42)
        sample_b = build_review_sample(cases, ans, ans, fraction=0.2, seed=42)
        # >=20% of 10 == at least 2 cases.
        self.assertGreaterEqual(len(sample_a), 2)
        # Deterministic with a fixed seed.
        self.assertEqual([p.case_id for p in sample_a], [p.case_id for p in sample_b])

    def test_fraction_out_of_range_is_rejected(self):
        cases = [_case("q1", "q", False)]
        for bad in (0.0, -0.1, 1.5):
            with self.assertRaises(ValueError):
                build_review_sample(cases, lambda q: "a", lambda q: "a", fraction=bad, seed=1)


class CompareCampaignsTests(unittest.TestCase):
    def test_reports_abstention_for_both_campaigns(self):
        cases = [
            _case("a1", "abstain please", True),
            _case("a2", "also abstain", True),
            _case("b1", "answer me", False),
        ]

        # RAG abstains on both abstention cases (good), answers b1.
        def rag_answer(question):
            return "grounded [S1]" if question == "answer me" else RAG_ABSTENTION

        # Closed-book abstains only on a1, hallucinates on a2 (bad recall).
        def closed_book_answer(question):
            if question == "abstain please":
                return CLOSED_BOOK_ABSTENTION
            return "made up answer"

        result = compare_campaigns(
            cases, rag_answer, closed_book_answer, review_fraction=1.0, seed=7
        )
        self.assertEqual(result.rag_abstention_recall, 1.0)      # 2/2
        self.assertAlmostEqual(result.closed_book_abstention_recall, 0.5)  # 1/2
        # Review sample covers all cases at fraction 1.0.
        self.assertEqual(len(result.review_sample), 3)
        self.assertEqual(result.total, 3)

    def test_rejects_duplicate_case_id(self):
        cases = [_case("dup", "q1", False), _case("dup", "q2", True)]
        with self.assertRaises(ValueError):
            compare_campaigns(cases, lambda q: "a", lambda q: "a", review_fraction=0.2, seed=1)


if __name__ == "__main__":
    unittest.main()
