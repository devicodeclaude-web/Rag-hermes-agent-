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

    @staticmethod
    def _matches(point: dict, condition: dict) -> bool:
        if "has_id" in condition:
            return point["id"] in condition["has_id"]
        value = point["payload"].get(condition["key"])
        match = condition["match"]
        if "except" in match:
            return any(item not in match["except"] for item in value) if isinstance(value, list) else value not in match["except"]
        return match["value"] in value if isinstance(value, list) else value == match["value"]

    def delete_points(self, collection: str, query_filter: dict) -> dict:
        for point_id in list(self.points):
            point = self.points[point_id]
            if all(self._matches(point, c) for c in query_filter["must"]) and not any(
                self._matches(point, c) for c in query_filter.get("must_not", [])
            ):
                del self.points[point_id]
        return {"status": "ok", "result": {"status": "completed"}}

    def upsert(self, collection: str, points: list[dict], *, update_filter: dict | None = None) -> dict:
        for point in points:
            existing = self.points.get(point["id"])
            if existing is not None and update_filter is not None:
                if not all(self._matches(existing, c) for c in update_filter["must"]) or any(
                    self._matches(existing, c) for c in update_filter.get("must_not", [])
                ):
                    continue
            self.points[point["id"]] = point
        return {"status": "ok", "result": {"status": "completed"}}

    def retrieve_points(self, collection: str, ids: list[str]) -> list[dict]:
        return [self.points[point_id] for point_id in ids if point_id in self.points]

    def query(self, collection, vector, *, query_filter, limit):
        # The fake returns everything; the repository postfilter enforces ACL.
        return [dict(point, score=1.0) for point in self.points.values()][:limit]

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

    def test_fake_scroll_does_not_invent_terminal_cursor(self) -> None:
        for index in range(3):
            self.client.points[str(index)] = {
                "id": str(index), "payload": {
                    "tenant_id": "alpha", "document_id": "guide",
                },
            }
        filtered = {"must": [
            {"key": "tenant_id", "match": {"value": "alpha"}},
        ]}
        first, cursor = self.client.scroll_filtered_page(
            "hermes_chunks_v1", query_filter=filtered, limit=2
        )
        self.assertEqual(len(first), 2)
        self.assertEqual(cursor, "2")
        last, terminal = self.client.scroll_filtered_page(
            "hermes_chunks_v1", query_filter=filtered, limit=2, offset=cursor
        )
        self.assertEqual([point["id"] for point in last], ["2"])
        self.assertIsNone(terminal)

    def test_fake_delete_honors_owner_filter(self) -> None:
        for owner in ("alice", "bob"):
            self.client.points[owner] = {
                "id": owner, "payload": {
                    "tenant_id": "alpha", "document_id": "guide",
                    "owner_id": owner,
                },
            }
        self.client.delete_points("hermes_chunks_v1", {"must": [
            {"key": "tenant_id", "match": {"value": "alpha"}},
            {"key": "document_id", "match": {"value": "guide"}},
            {"key": "owner_id", "match": {"value": "alice"}},
        ]})
        self.assertEqual(set(self.client.points), {"bob"})

    def test_replacement_preserves_foreign_scalar_owner_inserted_after_scan(self) -> None:
        def embed(_text: str) -> list[float]:
            self.client.points["bob"] = {"id": "bob", "payload": {
                "tenant_id": "alpha", "document_id": "guide", "owner_id": "bob",
            }}
            return [1.0, 0.0]

        repository = QdrantChunkRepository(
            self.client, collection="hermes_chunks_v1", embed=embed,
        )
        service = RagService(repository=repository)
        service.import_document(self.document, context=self.context)
        self.assertIn("bob", self.client.points)
        self.assertEqual(self.client.points["bob"]["payload"]["owner_id"], "bob")

    def test_fake_upsert_refuses_foreign_existing_point(self) -> None:
        client = FakeQdrantClient()
        client.points["p"] = {"id": "p", "payload": {"owner_id": "bob"}}
        attempted = {"id": "p", "payload": {"owner_id": "alice"}}
        client.upsert("chunks", [attempted], update_filter={"must": [
            {"key": "owner_id", "match": {"value": "alice"}},
        ]})
        self.assertEqual(client.points["p"]["payload"]["owner_id"], "bob")
        self.assertEqual(client.retrieve_points("chunks", ["p"]), [client.points["p"]])

    def test_second_import_completes_stale_point_deletion(self) -> None:
        from dataclasses import replace
        self.service.import_document(self.document, context=self.context)
        revised = replace(self.document, content="Nouvelle notice Hermes.", doc_version=2)
        result = self.service.import_document(revised, context=self.context)
        self.assertGreater(result.chunk_count, 0)
        self.assertEqual(
            {point["payload"]["text"] for point in self.client.points.values()},
            {"Nouvelle notice Hermes."},
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
