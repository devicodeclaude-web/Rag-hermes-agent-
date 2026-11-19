from __future__ import annotations

from fractions import Fraction
import unittest

from rag_hermes import g1_reranking, reranker_scores, service
from rag_hermes.reranker_scores import RerankerScoreError, ensure_finite_scores


class EnsureFiniteScoresTests(unittest.TestCase):
    def test_valid_scores_are_returned_as_floats(self) -> None:
        scores = ensure_finite_scores([1, 0.5, Fraction(1, 4)], 3)
        self.assertEqual(scores, [1.0, 0.5, 0.25])
        self.assertTrue(all(type(score) is float for score in scores))

    def test_wrong_count_is_refused(self) -> None:
        for values, expected in (([1.0], 2), ([1.0, 2.0, 3.0], 2), ([], 1)):
            with self.subTest(values=values, expected=expected):
                with self.assertRaises(RerankerScoreError):
                    ensure_finite_scores(values, expected)

    def test_non_finite_scores_are_refused(self) -> None:
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(score=bad):
                with self.assertRaises(RerankerScoreError):
                    ensure_finite_scores([bad, 0.5], 2)

    def test_booleans_are_refused(self) -> None:
        # `True` est un int en Python : accepté, il se classerait comme 1.0 et
        # un reranker cassé renvoyant des booléens passerait inaperçu.
        with self.assertRaises(RerankerScoreError):
            ensure_finite_scores([True, False], 2)

    def test_non_numeric_values_are_refused(self) -> None:
        for bad in ("0.9", None, [0.9], {"score": 0.9}, object()):
            with self.subTest(value=bad):
                with self.assertRaises(RerankerScoreError):
                    ensure_finite_scores([bad, 0.5], 2)

    def test_float_conversion_overflow_is_refused(self) -> None:
        huge = 10 ** 400  # int fini mais non représentable en float
        with self.assertRaises(RerankerScoreError):
            ensure_finite_scores([huge, 0.5], 2)

    def test_empty_expectation_accepts_empty_scores(self) -> None:
        self.assertEqual(ensure_finite_scores([], 0), [])


class SharedGuardTests(unittest.TestCase):
    def test_v1_and_g1_share_the_same_finiteness_guard(self) -> None:
        # L'audit CODE-01 vient précisément d'une divergence : G1 vérifiait
        # `math.isfinite`, la V1 non. Épingler l'identité de la fonction
        # empêche les deux chemins de redivorcer silencieusement.
        self.assertIs(service.ensure_finite_scores, reranker_scores.ensure_finite_scores)
        self.assertIs(
            g1_reranking.ensure_finite_scores, reranker_scores.ensure_finite_scores
        )


if __name__ == "__main__":
    unittest.main()
