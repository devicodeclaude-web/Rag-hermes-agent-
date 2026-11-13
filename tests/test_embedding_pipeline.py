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

    @staticmethod
    def _matches(point: dict, condition: dict) -> bool:
        if "has_id" in condition:
            return point["id"] in condition["has_id"]
        value = point["payload"].get(condition["key"])
        match = condition["match"]
        if "except" in match:
            return any(item not in match["except"] for item in value) if isinstance(value, list) else value not in match["except"]
        return match["value"] in value if isinstance(value, list) else value == match["value"]

    def delete_points(self, collection, query_filter):
        for point_id in list(self.points):
            point = self.points[point_id]
            if all(self._matches(point, c) for c in query_filter["must"]) and not any(
                self._matches(point, c) for c in query_filter.get("must_not", [])
            ):
                del self.points[point_id]
        return {"status": "ok", "result": {"status": "completed"}}

    def upsert(self, collection, points, *, update_filter=None):
        for point in points:
            existing = self.points.get(point["id"])
            if existing is not None and update_filter is not None:
                if not all(self._matches(existing, c) for c in update_filter["must"]) or any(
                    self._matches(existing, c) for c in update_filter.get("must_not", [])
                ):
                    continue
            self.points[point["id"]] = point
        return {"status": "ok", "result": {"status": "completed"}}

    def retrieve_points(self, collection, ids):
        return [self.points[point_id] for point_id in ids if point_id in self.points]

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

    def test_fake_delete_confirms_completion(self) -> None:
        client = FakeQdrantClient()
        client.points["p"] = {"id": "p", "payload": {"owner_id": "alice"}}
        result = client.delete_points("chunks", {"must": [
            {"key": "owner_id", "match": {"value": "alice"}},
        ]})
        self.assertEqual(result["result"]["status"], "completed")
        self.assertEqual(client.points, {})

    def test_fake_upsert_refuses_foreign_existing_point(self) -> None:
        client = FakeQdrantClient()
        client.points["p"] = {"id": "p", "payload": {"owner_id": "bob"}}
        attempted = {"id": "p", "payload": {"owner_id": "alice"}}
        client.upsert("chunks", [attempted], update_filter={"must": [
            {"key": "owner_id", "match": {"value": "alice"}},
        ]})
        self.assertEqual(client.points["p"]["payload"]["owner_id"], "bob")
        self.assertEqual(client.retrieve_points("chunks", ["p"]), [client.points["p"]])

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
