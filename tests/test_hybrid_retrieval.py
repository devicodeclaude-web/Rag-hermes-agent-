import unittest

from rag_hermes.retrieval import hybrid_rrf_indices


class HybridRetrievalTests(unittest.TestCase):
    def test_dense_and_sparse_lists_are_bounded_deduplicated_and_fused(self):
        ranked = hybrid_rrf_indices(
            candidate_indices=[10, 11, 12, 13],
            dense_scores=[0.9, 0.8, 0.1, 0.0],
            sparse_scores=[0.0, 0.7, 1.0, 0.6],
            dense_limit=2,
            sparse_limit=3,
            output_limit=3,
            fusion_k=60,
            dense_weight=1.0,
            sparse_weight=1.0,
        )
        self.assertEqual(len(ranked), 3)
        self.assertEqual(len(set(ranked)), 3)
        self.assertEqual(ranked[0], 11)
        self.assertTrue(set(ranked).issubset({10, 11, 12, 13}))


if __name__ == "__main__":
    unittest.main()
