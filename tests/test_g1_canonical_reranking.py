"""Reranking stage over canonical candidates; still no answer and no abstention."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_store import chunk_to_point
from tests.test_qdrant_hybrid_candidates import HybridQueryClient


class FakeTokenizer:
    def __init__(self, length: int = 10) -> None:
        self.length = length
        self.pairs: list[tuple[str, str]] = []

    def __call__(self, query, passage, **kwargs):
        self.pairs.append((query, passage))
        return {"input_ids": list(range(self.length))}


class FakeReranker:
    def __init__(self, scores) -> None:
        self.scores = scores
        self.calls: list[dict] = []

    def compute_score(self, pairs, **kwargs):
        self.calls.append({"pairs": pairs, **kwargs})
        return self.scores


class CanonicalRerankingTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "source.jsonl"
        self.doc = Document(
            document_id="guide", content="Installez Hermes avec pipx.",
            tenant_id="alpha", visibility="private", owner_id="alice",
            allowed_groups=(), allowed_users=(), classification=1,
            doc_version=1, source_uri="file:///guide.md",
        )
        self.context = AuthorizationContext("alpha", "alice", (), 1)
        self.client = HybridQueryClient()
        self.repo = QdrantChunkRepository(
            self.client, collection="chunks", embed=lambda text: [1.0, 0.0],
            embed_hybrid=lambda text: ([1.0, 0.0], {"7": 0.5}),
        )

    def source_with(self, *documents: Document, indexed: tuple[Document, ...] | None = None):
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        self.client.dense_results = [
            {**chunk_to_point(chunk_document(document)[0], [1.0, 0.0]),
             "score": 0.9 - index / 100}
            for index, document in enumerate(indexed or documents)
        ]
        self.path.write_text("".join(
            json.dumps(asdict(document), ensure_ascii=False) + "\n"
            for document in documents
        ), encoding="utf-8")
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        return CanonicalHybridCandidates(self.repo, self.path, expected_sha256=digest)

    def staged(self, source, scores, *, tokenizer=None, **options):
        from rag_hermes.g1_reranking import RerankedCandidateSource
        self.reranker = FakeReranker(scores)
        self.tokenizer = tokenizer or FakeTokenizer()
        return RerankedCandidateSource(
            source, self.reranker, self.tokenizer, **options
        )

    def test_reranker_reorders_without_widening_authorization(self) -> None:
        second = replace(self.doc, document_id="autre", content="Autre passage canonique.")
        staged = self.staged(self.source_with(self.doc, second), [0.1, 0.9], top_k=2)

        found = staged.candidates("question", context=self.context)

        self.assertEqual([item.chunk.document_id for item in found], ["autre", "guide"])
        self.assertEqual([item.rerank_score for item in found], [0.9, 0.1])
        self.assertEqual(self.reranker.calls[0]["max_length"], 512)
        self.assertEqual(self.reranker.calls[0]["batch_size"], 1)
        self.assertTrue(self.reranker.calls[0]["normalize"])
        self.assertEqual(len(self.reranker.calls), 1)
        self.assertEqual(
            self.tokenizer.pairs,
            [("question", self.doc.content), ("question", second.content)],
        )

    def test_top_k_truncates_after_reranking_not_before(self) -> None:
        second = replace(self.doc, document_id="autre", content="Autre passage canonique.")
        staged = self.staged(self.source_with(self.doc, second), [0.1, 0.9], top_k=1)
        found = staged.candidates("question", context=self.context)
        self.assertEqual([item.chunk.document_id for item in found], ["autre"])

    def test_rrf_score_is_preserved_next_to_the_rerank_score(self) -> None:
        staged = self.staged(self.source_with(self.doc), [0.42])
        found = staged.candidates("question", context=self.context)
        self.assertEqual(found[0].rerank_score, 0.42)
        self.assertGreater(found[0].rrf_score, 0)
        self.assertLess(found[0].rrf_score, 0.2)

    def test_wrong_score_count_fails_closed(self) -> None:
        second = replace(self.doc, document_id="autre", content="Autre passage canonique.")
        for scores in ([0.9], [0.1, 0.2, 0.3], []):
            with self.subTest(scores=scores):
                staged = self.staged(self.source_with(self.doc, second), scores)
                with self.assertRaisesRegex(ValueError, "one finite score per pair"):
                    staged.candidates("question", context=self.context)

    def test_non_finite_or_non_numeric_score_fails_closed(self) -> None:
        for scores in ([float("nan")], [float("inf")], ["0.9"], [None]):
            with self.subTest(scores=scores):
                staged = self.staged(self.source_with(self.doc), scores)
                with self.assertRaises((ValueError, TypeError)):
                    staged.candidates("question", context=self.context)

    def test_numpy_real_scores_from_an_injected_cross_encoder_are_accepted(self) -> None:
        import numpy as np
        second = replace(self.doc, document_id="autre", content="Autre passage canonique.")
        staged = self.staged(
            self.source_with(self.doc, second),
            np.array([0.25, 0.75], dtype=np.float32), top_k=2,
        )
        found = staged.candidates("question", context=self.context)
        self.assertEqual([item.chunk.document_id for item in found], ["autre", "guide"])

    def test_numpy_scalar_score_from_injected_cross_encoder_is_accepted(self) -> None:
        import numpy as np
        staged = self.staged(self.source_with(self.doc), np.float32(0.25))
        found = staged.candidates("question", context=self.context)
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0].rerank_score, 0.25)

    def test_float_subclass_converting_to_infinity_fails_closed(self) -> None:
        class ForgedFloat(float):
            def __float__(self):
                return float("inf")
        staged = self.staged(self.source_with(self.doc), [ForgedFloat(0.5)])
        with self.assertRaisesRegex(ValueError, "one finite score per pair"):
            staged.candidates("question", context=self.context)

    def test_float_conversion_overflow_is_a_validation_error(self) -> None:
        class OverflowingFloat(float):
            def __float__(self):
                raise OverflowError("not representable")
        staged = self.staged(self.source_with(self.doc), [OverflowingFloat(0.5)])
        with self.assertRaisesRegex(ValueError, "one finite score per pair"):
            staged.candidates("q", context=self.context)

    def test_float_conversion_mutating_pairs_is_refused(self) -> None:
        class MutatingFloat(float):
            def __new__(cls, value, pairs):
                return super().__new__(cls, value)
            def __init__(self, value, pairs):
                self.pairs = pairs
            def __float__(self):
                self.pairs[0][1] = "Texte non canonique"
                return 0.5
        source = self.source_with(self.doc)
        staged = self.staged(source, [])
        def score(pairs, **kwargs):
            return [MutatingFloat(0.5, pairs)]
        self.reranker.compute_score = score
        with self.assertRaisesRegex(ValueError, "one finite score per pair"):
            staged.candidates("q", context=self.context)

    def test_mutating_model_input_cannot_score_different_passages_silently(self) -> None:
        source = self.source_with(self.doc)
        staged = self.staged(source, [0.9])

        def mutate(pairs, **kwargs):
            pairs[0][1] = "Texte différent de la source canonique"
            return [0.9]

        self.reranker.compute_score = mutate
        with self.assertRaisesRegex(ValueError, "reranker modified scoring pairs"):
            staged.candidates("question", context=self.context)

    def test_one_oversized_pair_after_a_valid_pair_aborts_before_scoring(self) -> None:
        second = replace(self.doc, document_id="autre", content="Autre passage canonique.")
        source = self.source_with(self.doc, second)
        class SecondOversizedTokenizer(FakeTokenizer):
            def __call__(self, query, passage, **kwargs):
                self.pairs.append((query, passage))
                return {"input_ids": list(range(10 if len(self.pairs) == 1 else 513))}
        staged = self.staged(source, [0.1, 0.9], tokenizer=SecondOversizedTokenizer())
        with self.assertRaisesRegex(ValueError, "513.*512"):
            staged.candidates("q", context=self.context)
        self.assertEqual(len(self.tokenizer.pairs), 2)
        self.assertEqual(self.reranker.calls, [])

    def test_valid_zero_negative_and_scalar_scores(self) -> None:
        source = self.source_with(self.doc)
        for scores, expected in ((0.0, 0.0), (-0.5, -0.5), ([0.0], 0.0)):
            with self.subTest(scores=scores):
                staged = self.staged(source, scores, top_k=1, candidate_limit=1)
                found = staged.candidates("q", context=self.context)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0].rerank_score, expected)

    def test_unbounded_score_generator_is_cut_at_expected_plus_one(self) -> None:
        source = self.source_with(self.doc)
        seen = []
        def scores():
            while True:
                seen.append(1)
                yield 0.5
        staged = self.staged(source, scores())
        with self.assertRaisesRegex(ValueError, "one finite score per pair"):
            staged.candidates("q", context=self.context)
        self.assertEqual(len(seen), 2)

    def test_boolean_score_is_not_a_valid_number(self) -> None:
        staged = self.staged(self.source_with(self.doc), [True])
        with self.assertRaisesRegex(ValueError, "one finite score per pair"):
            staged.candidates("q", context=self.context)

    def test_pair_over_the_token_budget_is_rejected_not_truncated(self) -> None:
        staged = self.staged(
            self.source_with(self.doc), [0.9], tokenizer=FakeTokenizer(513),
        )
        with self.assertRaisesRegex(ValueError, "513.*512"):
            staged.candidates("question", context=self.context)
        self.assertEqual(self.reranker.calls, [])

    def test_empty_window_is_not_submitted_to_the_reranker(self) -> None:
        source = self.source_with(self.doc)
        self.client.dense_results = []
        staged = self.staged(source, [0.9])
        self.assertEqual(staged.candidates("question", context=self.context), [])
        self.assertEqual(self.reranker.calls, [])

    def test_ties_are_broken_deterministically_by_chunk_id(self) -> None:
        second = replace(self.doc, document_id="autre", content="Autre passage canonique.")
        source = self.source_with(self.doc, second)
        staged = self.staged(source, [0.5, 0.5], top_k=2)
        first_run = [item.chunk.chunk_id for item in staged.candidates("q", context=self.context)]
        second_run = [item.chunk.chunk_id for item in staged.candidates("q", context=self.context)]
        self.assertEqual(first_run, sorted(first_run))
        self.assertEqual(first_run, second_run)

    def test_invalid_wiring_is_refused_at_construction(self) -> None:
        from rag_hermes.g1_reranking import RerankedCandidateSource
        source = self.source_with(self.doc)
        with self.assertRaisesRegex(ValueError, "canonical candidate source"):
            RerankedCandidateSource(object(), FakeReranker([]), FakeTokenizer())
        with self.assertRaisesRegex(ValueError, "reranker and tokenizer"):
            RerankedCandidateSource(source, object(), FakeTokenizer())
        with self.assertRaisesRegex(ValueError, "reranker and tokenizer"):
            RerankedCandidateSource(source, FakeReranker([]), object())
        for option, value in (
            ("max_length", 513), ("max_length", 0), ("batch_size", 0),
            ("top_k", 0), ("top_k", 81), ("candidate_limit", 81),
            ("max_length", True), ("top_k", 2.0),
        ):
            with self.subTest(option=option, value=value):
                with self.assertRaisesRegex(ValueError, option):
                    RerankedCandidateSource(
                        source, FakeReranker([]), FakeTokenizer(), **{option: value},
                    )
        with self.assertRaisesRegex(ValueError, "top_k must not exceed"):
            RerankedCandidateSource(
                source, FakeReranker([]), FakeTokenizer(), top_k=5, candidate_limit=4,
            )

    def test_foreign_tenant_never_reaches_reranker_even_when_index_returns_it(self) -> None:
        secret = replace(self.doc, document_id="secret", tenant_id="beta", owner_id="bob")
        staged = self.staged(self.source_with(secret, self.doc), [0.8], top_k=1)
        found = staged.candidates("q", context=self.context)
        self.assertEqual([item.chunk.document_id for item in found], ["guide"])
        self.assertEqual(self.reranker.calls[0]["pairs"], [["q", self.doc.content]])

    def test_stale_acl_candidate_is_dropped_if_a_valid_one_remains(self) -> None:
        good = replace(self.doc, document_id="autre", content="Autre passage canonique.")
        indexed_stale = replace(self.doc, acl_version=1)
        canonical_stale = replace(self.doc, acl_version=2)
        staged = self.staged(
            self.source_with(canonical_stale, good, indexed=(indexed_stale, good)),
            [0.8], top_k=1,
        )
        found = staged.candidates("q", context=self.context)
        self.assertEqual([item.chunk.document_id for item in found], ["autre"])
        self.assertEqual(self.reranker.calls[0]["pairs"], [["q", good.content]])

    def test_canonical_divergence_still_aborts_before_reranking(self) -> None:
        # Index = propriétaire alice ; source canonique = propriétaire bob.
        source = self.source_with(
            replace(self.doc, owner_id="bob"), indexed=(self.doc,),
        )
        staged = self.staged(source, [0.9])
        with self.assertRaisesRegex(PermissionError, "observed ACL conflicts"):
            staged.candidates("question", context=self.context)
        self.assertEqual(self.reranker.calls, [])


if __name__ == "__main__":
    unittest.main()
