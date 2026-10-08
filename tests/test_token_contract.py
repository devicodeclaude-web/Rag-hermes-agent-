"""Lot 2 — contrat de tokens (Option A : rejet par paire + poursuite).

Ces tests encodent le contrat décidé :
- comptage exact question + passage + tokens spéciaux, sans troncature ;
- une paire hors budget est rejetée (journalisée : document + nb de tokens),
  les paires restantes sont tout de même scorées ;
- si TOUTES les paires dépassent le budget, erreur typée ERROR_TOKEN_BUDGET
  (RerankerBudgetExceeded), jamais une abstention ;
- budget de passage dérivé d'une marge de question NOMMÉE.

La logique est testée avec un tokenizer injecté (déterministe, sans réseau).
Les cas linguistiques réels (FR accentué, markdown/code) sont prouvés avec le
vrai tokenizer du reranker dans AUDIT/2026-10-08-token-contract/.
"""
from __future__ import annotations

import unittest

from rag_hermes.reranker_budget import (
    RejectedPair,
    RerankerBudgetExceeded,
    count_pair_tokens,
    pair_fits,
    passage_token_budget,
)
from rag_hermes.retrieval import score_authorized_pairs


class FixedTokenizer:
    """Rend des input_ids de longueur fixée par appel, dans l'ordre."""

    def __init__(self, lengths):
        self._lengths = list(lengths)
        self._index = 0
        self.calls = []

    def __call__(self, query, passage=None, **kwargs):
        self.calls.append((query, passage, kwargs))
        length = self._lengths[self._index]
        self._index += 1
        return {"input_ids": list(range(length))}


class FakeReranker:
    def __init__(self):
        self.calls = []

    def compute_score(self, pairs, **kwargs):
        self.calls.append((pairs, kwargs))
        return [0.5 for _ in pairs]


def _cand(doc, text="x"):
    return {"payload": {"document_id": doc, "text": text, "chunk_index": doc}}


class BudgetFunctionTests(unittest.TestCase):
    def test_pair_fits_at_512_true_at_513_false_without_truncation(self):
        tok = FixedTokenizer([512, 513])
        fits, count = pair_fits(tok, "q", "p", max_length=512)
        self.assertTrue(fits)
        self.assertEqual(count, 512)
        fits, count = pair_fits(tok, "q", "p", max_length=512)
        self.assertFalse(fits)
        self.assertEqual(count, 513)
        # jamais de troncature silencieuse ; tokens spéciaux comptés
        self.assertFalse(tok.calls[0][2]["truncation"])
        self.assertTrue(tok.calls[0][2]["add_special_tokens"])

    def test_count_pair_tokens_is_the_single_budget_source(self):
        tok = FixedTokenizer([400])
        self.assertEqual(count_pair_tokens(tok, "q", "p"), 400)
        self.assertFalse(tok.calls[0][2]["truncation"])
        self.assertTrue(tok.calls[0][2]["add_special_tokens"])

    def test_passage_budget_uses_named_question_margin(self):
        self.assertEqual(
            passage_token_budget(
                reranker_max_length=512,
                question_token_margin=96,
                special_token_reserve=32,
            ),
            384,
        )
        # 384 passage + 96 question + 32 special == 512, structurellement <= budget
        self.assertEqual(384 + 96 + 32, 512)

    def test_passage_budget_rejects_margins_that_leave_no_room(self):
        with self.assertRaises(ValueError):
            passage_token_budget(
                reranker_max_length=512,
                question_token_margin=500,
                special_token_reserve=100,
            )


class OptionARejectAndContinueTests(unittest.TestCase):
    def test_over_budget_pair_is_dropped_and_others_are_scored(self):
        tok = FixedTokenizer([10, 600, 20])
        reranker = FakeReranker()
        candidates = [_cand("a"), _cand("b"), _cand("c")]
        scores, counters = score_authorized_pairs(
            reranker, tok, "q", candidates, max_length=512, batch_size=8
        )
        # la paire "b" (600) est écartée, "a" et "c" sont scorées
        self.assertEqual(len(scores), 2)
        self.assertEqual(counters.checked_pairs, 3)
        self.assertEqual(counters.rejected_pairs, 1)
        self.assertEqual([c["payload"]["document_id"] for c in counters.scored], ["a", "c"])
        self.assertEqual(len(reranker.calls[0][0]), 2)

    def test_rejected_pairs_are_logged_with_document_and_token_count(self):
        tok = FixedTokenizer([10, 600, 20])
        reranker = FakeReranker()
        candidates = [_cand("a"), _cand("b"), _cand("c")]
        _, counters = score_authorized_pairs(
            reranker, tok, "q", candidates, max_length=512, batch_size=8
        )
        self.assertEqual(len(counters.rejected), 1)
        rejected = counters.rejected[0]
        self.assertIsInstance(rejected, RejectedPair)
        self.assertEqual(rejected.document_id, "b")
        self.assertEqual(rejected.token_count, 600)
        self.assertEqual(rejected.reason, "token_budget")

    def test_all_candidates_over_budget_raises_typed_error(self):
        tok = FixedTokenizer([600, 700])
        reranker = FakeReranker()
        candidates = [_cand("a"), _cand("b")]
        with self.assertRaisesRegex(RerankerBudgetExceeded, "all 2"):
            score_authorized_pairs(
                reranker, tok, "q", candidates, max_length=512, batch_size=8
            )
        # l'erreur n'exécute jamais le reranker
        self.assertEqual(reranker.calls, [])

    def test_no_candidate_returns_empty_without_error(self):
        tok = FixedTokenizer([])
        reranker = FakeReranker()
        scores, counters = score_authorized_pairs(
            reranker, tok, "q", [], max_length=512, batch_size=8
        )
        self.assertEqual(scores, [])
        self.assertEqual(counters.checked_pairs, 0)
        self.assertEqual(counters.rejected_pairs, 0)
        self.assertEqual(reranker.calls, [])


if __name__ == "__main__":
    unittest.main()
