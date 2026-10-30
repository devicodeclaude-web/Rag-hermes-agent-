from __future__ import annotations

import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_filter import build_qdrant_filter
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_store import chunk_to_point


class FakeQdrantClient:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, dict]] = []
        self.upserted: list[tuple[str, list[dict]]] = []
        self.queries: list[tuple[str, list[float], dict, int]] = []
        self.query_results: list[dict] = []
        self.scrolls: list[tuple[str, dict, int]] = []
        self.scroll_results: list[dict] = []
        self.fail_upsert = False

    def delete_points(self, collection: str, query_filter: dict) -> dict:
        self.deleted.append((collection, query_filter))
        return {"status": "ok"}

    def upsert(self, collection: str, points: list[dict]) -> dict:
        if self.fail_upsert:
            raise RuntimeError("simulated Qdrant upsert failure")
        self.upserted.append((collection, points))
        return {"status": "ok"}

    def query(
        self,
        collection: str,
        vector: list[float],
        *,
        query_filter: dict,
        limit: int,
    ) -> list[dict]:
        self.queries.append((collection, vector, query_filter, limit))
        return self.query_results

    def scroll(self, collection: str, *, query_filter: dict, limit: int = 1) -> list[dict]:
        self.scrolls.append((collection, query_filter, limit))
        return self.scroll_results


class QdrantSemanticsClient(FakeQdrantClient):
    """Emulate Qdrant match semantics for scalar and array payload values."""

    @staticmethod
    def _matches(payload: dict, condition: dict) -> bool:
        value = payload.get(condition["key"])
        expected = condition["match"]["value"]
        if isinstance(value, list):
            return expected in value
        return value == expected

    def scroll(self, collection: str, *, query_filter: dict, limit: int = 1) -> list[dict]:
        self.scrolls.append((collection, query_filter, limit))
        matches = []
        for point in self.scroll_results:
            payload = point.get("payload", {})
            if not all(self._matches(payload, condition) for condition in query_filter["must"]):
                continue
            if any(
                self._matches(payload, condition)
                for condition in query_filter.get("must_not", [])
            ):
                continue
            matches.append(point)
        return matches[:limit]


class QdrantChunkRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeQdrantClient()
        self.document = Document(
            document_id="guide",
            content="Installer Hermes avec pipx install hermes-agent.",
            tenant_id="alpha",
            visibility="private",
            owner_id="alice",
            allowed_groups=("support",),
            allowed_users=(),
            classification=1,
            doc_version=1,
            source_uri="local://guide",
        )
        self.repository = QdrantChunkRepository(
            self.client,
            collection="hermes_chunks_v1",
            embed=lambda text: [float(len(text)), 1.0],
        )

    def test_replace_document_upserts_new_chunks_before_deleting_stale_points(self) -> None:
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)

        result = self.repository.replace_document(self.document, chunks)

        self.assertEqual(result.document_id, "guide")
        self.assertEqual(result.chunk_count, len(chunks))
        # Upsert happens first (compensating order), then a scoped delete.
        collection, points = self.client.upserted[0]
        self.assertEqual(collection, "hermes_chunks_v1")
        self.assertEqual(len(points), len(chunks))
        self.assertTrue(all(point["payload"]["owner_id"] == "alice" for point in points))
        new_ids = [point["id"] for point in points]
        self.assertEqual(
            self.client.deleted,
            [
                (
                    "hermes_chunks_v1",
                    {
                        "must": [
                            {"key": "tenant_id", "match": {"value": "alpha"}},
                            {"key": "document_id", "match": {"value": "guide"}},
                        ],
                        "must_not": [{"has_id": new_ids}],
                    },
                )
            ],
        )

    def test_search_prefilters_in_qdrant_and_postfilters_returned_candidates(self) -> None:
        alpha_chunk = chunk_document(self.document)[0]
        beta_document = Document(
            document_id="beta-secret",
            content="Installer le secret Beta.",
            tenant_id="beta",
            visibility="private",
            owner_id="bob",
            allowed_groups=(),
            allowed_users=(),
            classification=1,
            doc_version=1,
            source_uri="local://beta",
        )
        beta_chunk = chunk_document(beta_document)[0]
        alpha_point = chunk_to_point(alpha_chunk, [1.0, 0.0])
        beta_point = chunk_to_point(beta_chunk, [1.0, 0.0])
        alpha_point["score"] = 0.8
        beta_point["score"] = 0.99
        self.client.query_results = [beta_point, alpha_point]
        context = AuthorizationContext("alpha", "alice", ("support",), 1)

        results = self.repository.search("Installer Hermes", context=context, limit=5)

        self.assertEqual(
            self.client.queries,
            [
                (
                    "hermes_chunks_v1",
                    [16.0, 1.0],
                    build_qdrant_filter(context),
                    5,
                )
            ],
        )
        self.assertEqual([result.chunk.document_id for result in results], ["guide"])
        self.assertEqual(results[0].score, 0.8)

    def test_failed_upsert_does_not_delete_existing_document(self) -> None:
        chunks = chunk_document(self.document)
        self.client.fail_upsert = True

        with self.assertRaisesRegex(RuntimeError, "upsert failure"):
            self.repository.replace_document(self.document, chunks)

        self.assertEqual(self.client.deleted, [])

    def test_replace_refuses_persisted_different_owner_before_any_mutation(self) -> None:
        self.client.scroll_results = [
            {
                "id": "existing-point",
                "payload": {
                    "tenant_id": "alpha",
                    "document_id": "guide",
                    "owner_id": "alice",
                },
            }
        ]
        hijacked = Document(
            document_id="guide",
            content="Tentative de remplacement.",
            tenant_id="alpha",
            visibility="private",
            owner_id="bob",
            allowed_groups=("support",),
            allowed_users=(),
            classification=1,
            doc_version=2,
            source_uri="local://hijacked",
        )

        with self.assertRaisesRegex(PermissionError, "owner"):
            self.repository.replace_document(hijacked, chunk_document(hijacked))

        self.assertEqual(
            self.client.scrolls,
            [
                (
                    "hermes_chunks_v1",
                    {
                        "must": [
                            {"key": "tenant_id", "match": {"value": "alpha"}},
                            {"key": "document_id", "match": {"value": "guide"}},
                        ],
                    },
                    10_000,
                )
            ],
        )
        self.assertEqual(self.client.upserted, [])
        self.assertEqual(self.client.deleted, [])

    def test_replace_refuses_array_owner_payload_before_any_mutation(self) -> None:
        client = QdrantSemanticsClient()
        client.scroll_results = [
            {
                "id": "corrupt-point",
                "payload": {
                    "tenant_id": "alpha",
                    "document_id": "guide",
                    "owner_id": ["alice", "bob"],
                },
            }
        ]
        embed_calls: list[str] = []
        repository = QdrantChunkRepository(
            client,
            collection="hermes_chunks_v1",
            embed=lambda text: embed_calls.append(text) or [1.0, 1.0],
        )
        hijacked = Document(
            document_id="guide",
            content="Tentative de remplacement.",
            tenant_id="alpha",
            visibility="private",
            owner_id="bob",
            allowed_groups=("support",),
            allowed_users=(),
            classification=1,
            doc_version=2,
            source_uri="local://hijacked",
        )

        with self.assertRaisesRegex(PermissionError, "owner"):
            repository.replace_document(hijacked, chunk_document(hijacked))

        self.assertEqual(embed_calls, [])
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])


if __name__ == "__main__":
    unittest.main()
