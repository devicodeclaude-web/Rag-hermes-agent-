import unittest

from rag_hermes.reranker_budget import assert_pair_fits


class FakeTokenizer:
    def __init__(self, length):
        self.length = length
        self.calls = []

    def __call__(self, query, passage, **kwargs):
        self.calls.append((query, passage, kwargs))
        return {"input_ids": list(range(self.length))}


class RerankerBudgetTests(unittest.TestCase):
    def test_pair_within_budget_returns_exact_token_count(self):
        tokenizer = FakeTokenizer(511)
        self.assertEqual(assert_pair_fits(tokenizer, "q", "p", max_length=512), 511)
        self.assertFalse(tokenizer.calls[0][2]["truncation"])
        self.assertTrue(tokenizer.calls[0][2]["add_special_tokens"])

    def test_pair_over_budget_is_rejected_without_truncation(self):
        tokenizer = FakeTokenizer(513)
        with self.assertRaisesRegex(ValueError, "513.*512"):
            assert_pair_fits(tokenizer, "q", "p", max_length=512)

    def test_non_positive_budget_is_invalid(self):
        with self.assertRaises(ValueError):
            assert_pair_fits(FakeTokenizer(1), "q", "p", max_length=0)


if __name__ == "__main__":
    unittest.main()
