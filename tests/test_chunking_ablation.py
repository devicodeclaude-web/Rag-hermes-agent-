import unittest

from rag_hermes.chunking_ablation import (
    count_pairs_over_budget,
    estimate_pair_tokens,
)


class ChunkingAblationTests(unittest.TestCase):
    def test_large_word_chunk_exceeds_reranker_window(self):
        # 420 mots * 1.4 = 588 tokens + question + special -> > 512
        tokens = estimate_pair_tokens(
            420, 8, words_to_tokens=1.4, special_tokens=4
        )
        self.assertGreater(tokens, 512)

    def test_token_bounded_chunk_stays_within_window(self):
        # chunk deja borne a ~274 mots (~384 tokens) reste sous 512
        tokens = estimate_pair_tokens(
            274, 8, words_to_tokens=1.4, special_tokens=4
        )
        self.assertLessEqual(tokens, 512)

    def test_counts_only_over_budget_pairs(self):
        counts = [420, 420, 100]
        over = count_pairs_over_budget(
            counts, 8, max_length=512, words_to_tokens=1.4, special_tokens=4
        )
        self.assertEqual(over, 2)

    def test_ratio_must_be_positive(self):
        with self.assertRaises(ValueError):
            estimate_pair_tokens(1, 1, words_to_tokens=0, special_tokens=0)


if __name__ == "__main__":
    unittest.main()
