"""R3 candidate fusion in Qdrant; not a calibrated answer path."""
from __future__ import annotations

import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_store import chunk_to_point
from tests.test_qdrant_repository import FakeHybridClient


class HybridQueryClient(FakeHybridClient):
    def __init__(self) -> None:
        super().__init__()
        self.dense_results = []
        self.sparse_results = []
        self.sparse_queries = []

    def query(self, collection, vector, *, query_filter, limit):
        self.queries.append((collection, vector, query_filter, limit))
        return self.dense_results[:limit]

    def query_sparse(self, collection, lexical_weights, *, context, limit):
        self.sparse_queries.append((collection, lexical_weights, context, limit))
        return self.sparse_results[:limit]


class HybridCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = HybridQueryClient()
        self.context = AuthorizationContext("alpha", "alice", (), 1)
        self.encodes = []

        def embed_hybrid(text):
            self.encodes.append(text)
            return [1.0, 0.0], {"7": 0.5}

        self.repo = QdrantChunkRepository(
            self.client, collection="chunks", embed=lambda text: [1.0, 0.0],
            embed_hybrid=embed_hybrid,
        )

    def point(self, doc_id: str, *, tenant: str = "alpha") -> dict:
        doc = Document(
            document_id=doc_id, content=f"Contenu {doc_id}.",
            tenant_id=tenant, visibility="private", owner_id="alice",
            allowed_groups=(), allowed_users=(), classification=1,
            doc_version=1, source_uri=f"local://{doc_id}",
        )
        return chunk_to_point(chunk_document(doc)[0], [1.0, 0.0])

    def test_two_lanes_are_prefiltered_fused_and_deduplicated(self) -> None:
        a, b, c = (self.point(value) for value in ("a", "b", "c"))
        self.client.dense_results = [{**a, "score": 0.9}, {**b, "score": 0.8}]
        self.client.sparse_results = [{**b, "score": 8.0}, {**c, "score": 4.0}]

        ranked = self.repo.hybrid_candidates("question", context=self.context, output_limit=3)

        self.assertEqual([item.chunk.document_id for item in ranked], ["b", "a", "c"])
        for candidate, expected in zip(ranked, (1 / 62 + 1 / 61, 1 / 61, 1 / 62)):
            self.assertAlmostEqual(candidate.rrf_score, expected)
        self.assertEqual(len(self.encodes), 1)
        self.assertEqual(self.client.queries[0][:2], ("chunks", [1.0, 0.0]))
        self.assertEqual(self.client.queries[0][3], 40)
        self.assertEqual(self.client.sparse_queries, [("chunks", {"7": 0.5}, self.context, 40)])
        self.assertEqual(
            self.client.queries[0][2]["min_should"]["conditions"][0]["must"][0],
            {"key": "tenant_id", "match": {"value": "alpha"}},
        )

    def test_unauthorized_top_candidate_does_not_hide_authorized_one(self) -> None:
        foreign, valid = self.point("foreign", tenant="beta"), self.point("valid")
        self.client.dense_results = [{**foreign, "score": 0.9}, {**valid, "score": 0.8}]
        self.client.sparse_results = []
        ranked = self.repo.hybrid_candidates("question", context=self.context, output_limit=1)
        self.assertEqual([item.chunk.document_id for item in ranked], ["valid"])

    def test_denied_candidates_are_opt_in_and_flagged(self) -> None:
        foreign, valid = self.point("foreign", tenant="beta"), self.point("valid")
        self.client.dense_results = [{**foreign, "score": 0.9}, {**valid, "score": 0.8}]
        default = self.repo.hybrid_candidates("question", context=self.context)
        self.assertEqual([item.chunk.document_id for item in default], ["valid"])
        self.assertEqual([item.authorized_by_index for item in default], [True])
        with_denied = self.repo.hybrid_candidates(
            "question", context=self.context, include_denied=True,
        )
        self.assertEqual(
            [(item.chunk.document_id, item.authorized_by_index) for item in with_denied],
            [("foreign", False), ("valid", True)],
        )

    def test_include_denied_must_be_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "include_denied"):
            self.repo.hybrid_candidates("question", context=self.context, include_denied=1)

    def test_malformed_authorization_context_fails_before_encoding(self) -> None:
        invalid = AuthorizationContext("alpha", "alice", (), True)
        with self.assertRaisesRegex(ValueError, "authorization context"):
            self.repo.hybrid_candidates("question", context=invalid)
        self.assertEqual(self.encodes, [])
        self.assertEqual(self.client.queries, [])
        self.assertEqual(self.client.sparse_queries, [])

    def test_forged_foreign_point_fails_before_acl_can_hide_it(self) -> None:
        foreign = self.point("foreign", tenant="beta")
        foreign["id"] = self.point("valid")["id"]
        self.client.dense_results = [{**foreign, "score": 0.9}]
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.repo.hybrid_candidates("question", context=self.context)

    def test_duplicate_within_one_lane_is_not_silently_fused(self) -> None:
        point = {**self.point("a"), "score": 0.9}
        self.client.dense_results = [point, point]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.repo.hybrid_candidates("question", context=self.context)

    def test_invalid_score_cannot_become_an_empty_answer(self) -> None:
        self.client.sparse_results = [{**self.point("a"), "score": True}]
        with self.assertRaisesRegex(ValueError, "score"):
            self.repo.hybrid_candidates("question", context=self.context)

    def test_conflicting_duplicate_point_across_lanes_fails_closed(self) -> None:
        original = self.point("a")
        forged = {**original, "payload": {**original["payload"], "text": "falsifié"}}
        self.client.dense_results = [{**original, "score": 0.9}]
        self.client.sparse_results = [{**forged, "score": 8.0}]
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.repo.hybrid_candidates("question", context=self.context)


if __name__ == "__main__":
    unittest.main()
