from __future__ import annotations

import unittest

from rag_hermes.acl import AuthorizationContext, Chunk
from rag_hermes.dense_report import build_qdrant_answer_fn
from rag_hermes.evaluation_runner import RetrievedChunk
from rag_hermes.retrieval import SearchResult


def _chunk(chunk_id: str, document_id: str, text: str, start: int, end: int) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        tenant_id="public",
        visibility="public",
        allowed_groups=(),
        allowed_users=(),
        owner_id="evaluator",
        classification=0,
        doc_version=1,
        source_sha="a" * 64,
        start_offset=start,
        end_offset=end,
    )


class _FakeRepository:
    """Stand-in for QdrantChunkRepository.search used to test the adapter purely."""

    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results
        self.calls: list[tuple[str, AuthorizationContext, int]] = []

    def search(self, query, *, context, limit=10):
        self.calls.append((query, context, limit))
        return list(self._results[:limit])


def _context(_case):
    return AuthorizationContext("public", "evaluator", (), 0)


class DenseAnswerFnTests(unittest.TestCase):
    def test_returns_retrieved_cited_and_not_abstained_above_threshold(self) -> None:
        chunk = _chunk("c1", "doc-a", "hello world", 0, 11)
        repo = _FakeRepository([SearchResult(chunk=chunk, score=0.9)])
        answer_fn = build_qdrant_answer_fn(
            repo, _context, minimum_score=0.05, limit=10
        )

        retrieved, cited, abstained = answer_fn("hello", {"case_id": "x"})

        self.assertEqual([rc.chunk for rc in retrieved], [chunk])
        self.assertEqual([rc.chunk for rc in cited], [chunk])
        self.assertFalse(abstained)
        self.assertIsInstance(retrieved[0], RetrievedChunk)
        # Adapter must forward the configured limit to the repository.
        self.assertEqual(repo.calls[0][2], 10)

    def test_abstains_and_cites_nothing_when_all_below_threshold(self) -> None:
        chunk = _chunk("c1", "doc-a", "hello world", 0, 11)
        repo = _FakeRepository([SearchResult(chunk=chunk, score=0.01)])
        answer_fn = build_qdrant_answer_fn(
            repo, _context, minimum_score=0.05, limit=10
        )

        retrieved, cited, abstained = answer_fn("hello", {"case_id": "x"})

        # Retrieval still exposes what Qdrant returned (for leak accounting),
        # but nothing is cited and the system abstains.
        self.assertEqual([rc.chunk for rc in retrieved], [chunk])
        self.assertEqual(list(cited), [])
        self.assertTrue(abstained)

    def test_cites_only_chunks_at_or_above_threshold(self) -> None:
        keep = _chunk("c1", "doc-a", "hello world", 0, 11)
        drop = _chunk("c2", "doc-b", "other text!", 0, 11)
        repo = _FakeRepository(
            [
                SearchResult(chunk=keep, score=0.8),
                SearchResult(chunk=drop, score=0.02),
            ]
        )
        answer_fn = build_qdrant_answer_fn(
            repo, _context, minimum_score=0.05, limit=10
        )

        retrieved, cited, abstained = answer_fn("hello", {"case_id": "x"})

        self.assertEqual([rc.chunk for rc in retrieved], [keep, drop])
        self.assertEqual([rc.chunk for rc in cited], [keep])
        self.assertFalse(abstained)

    def test_rejects_non_authorization_context(self) -> None:
        repo = _FakeRepository([])
        answer_fn = build_qdrant_answer_fn(
            repo, lambda _case: "not-a-context", minimum_score=0.05, limit=10
        )
        with self.assertRaises(ValueError):
            answer_fn("hello", {"case_id": "x"})


if __name__ == "__main__":
    unittest.main()
