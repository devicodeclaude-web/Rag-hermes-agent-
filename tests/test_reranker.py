from __future__ import annotations

import unittest

from rag_hermes.acl import Chunk
from rag_hermes.reranker import BudgetedCrossEncoderReranker
from rag_hermes.reranker_budget import RerankerBudgetExceeded


def make_chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="doc",
        text=text,
        tenant_id="alpha",
        visibility="private",
        owner_id="alice",
        allowed_groups=("support",),
        allowed_users=(),
        classification=1,
        acl_version=1,
        doc_version=1,
        source_sha="a" * 64,
        source_uri="file:///doc.md",
    )


class FakeTokenizer:
    def __init__(self, lengths):
        self.lengths = list(lengths)
        self.calls = []

    def __call__(self, query, passage, **kwargs):
        self.calls.append((query, passage, kwargs))
        return {"input_ids": list(range(self.lengths[len(self.calls) - 1]))}


class FakeCrossEncoder:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def compute_score(self, pairs, **kwargs):
        self.calls.append((pairs, kwargs))
        return list(self.scores)


class BudgetedCrossEncoderRerankerTests(unittest.TestCase):
    def test_returns_one_score_per_chunk_and_enforces_budget(self) -> None:
        tokenizer = FakeTokenizer([10, 20])
        model = FakeCrossEncoder([0.9, 0.1])
        reranker = BudgetedCrossEncoderReranker(
            model=model, tokenizer=tokenizer, max_length=512, batch_size=8
        )
        chunks = (make_chunk("c1", "premier passage"), make_chunk("c2", "second"))

        scores = reranker("Comment installer ?", chunks)

        self.assertEqual(scores, [0.9, 0.1])
        # Pair budget was checked with the exact tokenizer, no truncation.
        self.assertFalse(tokenizer.calls[0][2]["truncation"])
        self.assertEqual(model.calls[0][1]["max_length"], 512)

    def test_pair_over_budget_is_rejected_before_scoring(self) -> None:
        tokenizer = FakeTokenizer([513])
        model = FakeCrossEncoder([0.5])
        reranker = BudgetedCrossEncoderReranker(
            model=model, tokenizer=tokenizer, max_length=512, batch_size=8
        )
        chunks = (make_chunk("c1", "passage trop long"),)

        with self.assertRaises(RerankerBudgetExceeded):
            reranker("q", chunks)

        # The model must never be called when a pair exceeds the budget.
        self.assertEqual(model.calls, [])

    def test_empty_candidates_returns_empty_scores_without_calling_model(self) -> None:
        tokenizer = FakeTokenizer([])
        model = FakeCrossEncoder([])
        reranker = BudgetedCrossEncoderReranker(
            model=model, tokenizer=tokenizer, max_length=512, batch_size=8
        )

        self.assertEqual(reranker("q", ()), [])
        self.assertEqual(model.calls, [])


if __name__ == "__main__":
    unittest.main()
