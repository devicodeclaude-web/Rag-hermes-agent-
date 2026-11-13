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
        for point_id in list(self.points):
            payload = self.points[point_id]["payload"]
            def matches(condition):
                if "has_id" in condition:
                    return point_id in condition["has_id"]
                value = payload.get(condition["key"])
                expected = condition["match"]["value"]
                return expected in value if isinstance(value, list) else value == expected

            if all(matches(c) for c in query_filter["must"]) and not any(
                matches(c) for c in query_filter.get("must_not", [])
            ):
                del self.points[point_id]
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

    def scroll_filtered_page(self, collection, *, query_filter, limit=1, offset=None):
        points = sorted(
            self.scroll(collection, query_filter=query_filter, limit=len(self.points)),
            key=lambda point: point["id"],
        )
        if offset is not None:
            points = [point for point in points if point["id"] >= offset]
        cursor = points[limit]["id"] if len(points) > limit else None
        return points[:limit], cursor


class LockedEmbedderPipelineTests(unittest.TestCase):
    def test_fake_delete_honors_owner_filter(self) -> None:
        client = FakeQdrantClient()
        for owner in ("alice", "bob"):
            client.points[owner] = {
                "id": owner, "payload": {
                    "tenant_id": "alpha", "document_id": "guide",
                    "owner_id": owner,
                },
            }
        client.delete_points("hermes_chunks_v1", {"must": [
            {"key": "tenant_id", "match": {"value": "alpha"}},
            {"key": "document_id", "match": {"value": "guide"}},
            {"key": "owner_id", "match": {"value": "alice"}},
        ]})
        self.assertEqual(set(client.points), {"bob"})

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
