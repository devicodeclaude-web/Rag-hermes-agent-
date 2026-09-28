from __future__ import annotations

import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.ingestion import Document
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.service import RagService


class FakeQdrantClient:
    """In-process double that behaves like QdrantRestClient for a single tenant."""

    def __init__(self) -> None:
        self.points: dict[str, dict] = {}

    def delete_points(self, collection: str, query_filter: dict) -> dict:
        must = query_filter["must"]
        tenant = must[0]["match"]["value"]
        document_id = must[1]["match"]["value"]
        keep_ids = set()
        for clause in query_filter.get("must_not", []):
            keep_ids.update(clause.get("has_id", []))
        for point_id in list(self.points):
            payload = self.points[point_id]["payload"]
            if (
                payload["tenant_id"] == tenant
                and payload["document_id"] == document_id
                and point_id not in keep_ids
            ):
                del self.points[point_id]
        return {"status": "ok"}

    def upsert(self, collection: str, points: list[dict]) -> dict:
        for point in points:
            self.points[point["id"]] = point
        return {"status": "ok"}

    def query(self, collection, vector, *, query_filter, limit):
        # The fake returns everything; the repository postfilter enforces ACL.
        return [dict(point, score=1.0) for point in self.points.values()][:limit]


class RagServiceQdrantBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeQdrantClient()
        repository = QdrantChunkRepository(
            self.client,
            collection="hermes_chunks_v1",
            embed=lambda text: [float(len(text)), 1.0],
        )
        self.service = RagService(repository=repository)
        self.context = AuthorizationContext("alpha", "alice", ("support",), 1)
        self.document = Document(
            document_id="guide",
            content="Pour installer Hermes, utilisez pipx install hermes-agent.",
            tenant_id="alpha",
            visibility="private",
            owner_id="alice",
            allowed_groups=("support",),
            allowed_users=(),
            classification=1,
            doc_version=1,
            source_uri="local://guide",
        )

    def test_import_persists_to_repository_and_answer_reads_it_back(self) -> None:
        imported = self.service.import_document(self.document, context=self.context)
        response = self.service.answer("installer Hermes", context=self.context)

        self.assertEqual(imported.document_id, "guide")
        self.assertGreater(len(self.client.points), 0)
        self.assertFalse(response.abstained)
        self.assertEqual(response.citations[0].document_id, "guide")

    def test_foreign_tenant_context_cannot_read_persisted_document(self) -> None:
        self.service.import_document(self.document, context=self.context)
        intruder = AuthorizationContext("beta", "bob", ("support",), 1)

        response = self.service.answer("installer Hermes", context=intruder)

        self.assertTrue(response.abstained)
        self.assertEqual(response.citations, ())


if __name__ == "__main__":
    unittest.main()
