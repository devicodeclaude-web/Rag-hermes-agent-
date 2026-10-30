from __future__ import annotations

import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.embedding import LockedBgeM3Embedder
from rag_hermes.ingestion import Document
from rag_hermes.service import RagService
from rag_hermes.qdrant_repository import QdrantChunkRepository


class FakeFlagModel:
    def encode(self, texts, **kwargs):
        # 1024-dim vector derived deterministically from text length.
        base = float((len(texts[0]) % 5) + 1)
        return {"dense_vecs": [[base] + [1.0] * 1023]}


class FakeQdrantClient:
    def __init__(self) -> None:
        self.points: dict[str, dict] = {}

    def delete_points(self, collection, query_filter):
        must = query_filter["must"]
        tenant = must[0]["match"]["value"]
        document_id = must[1]["match"]["value"]
        keep = set()
        for clause in query_filter.get("must_not", []):
            keep.update(clause.get("has_id", []))
        for pid in list(self.points):
            p = self.points[pid]["payload"]
            if p["tenant_id"] == tenant and p["document_id"] == document_id and pid not in keep:
                del self.points[pid]
        return {"status": "ok"}

    def upsert(self, collection, points):
        for point in points:
            self.points[point["id"]] = point
        return {"status": "ok"}

    def query(self, collection, vector, *, query_filter, limit):
        return [dict(p, score=1.0) for p in self.points.values()][:limit]

    def scroll(self, collection, *, query_filter, limit=1):
        matches = []
        for point in self.points.values():
            payload = point["payload"]
            if not all(
                payload[condition["key"]] == condition["match"]["value"]
                for condition in query_filter["must"]
            ):
                continue
            if any(
                payload[condition["key"]] == condition["match"]["value"]
                for condition in query_filter.get("must_not", [])
            ):
                continue
            matches.append(point)
        return matches[:limit]


class LockedEmbedderPipelineTests(unittest.TestCase):
    def test_locked_embedder_feeds_repository_and_answer_returns_1024_dim_backed_result(self) -> None:
        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json",
            model_loader=lambda **_: FakeFlagModel(),
        )
        client = FakeQdrantClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=embedder
        )
        service = RagService(repository=repository)
        context = AuthorizationContext("alpha", "alice", ("support",), 1)
        document = Document(
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

        service.import_document(document, context=context)
        response = service.answer("installer Hermes", context=context)

        # Every persisted point carries a 1024-dim dense vector from the embedder.
        for point in client.points.values():
            self.assertEqual(len(point["vector"]["dense"]), 1024)
        self.assertFalse(response.abstained)
        self.assertEqual(response.citations[0].document_id, "guide")


if __name__ == "__main__":
    unittest.main()
