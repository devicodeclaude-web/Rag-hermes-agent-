"""Lecture seule préalable au marquage #71 ; ce plan n'autorise aucune mutation."""
from __future__ import annotations

import tempfile
import unittest
import uuid
from unittest.mock import patch

import rag_hermes.qdrant_repository as repository_module
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_store import chunk_to_point, stable_point_id
from tests.test_qdrant_repository import FakeQdrantClient


def _document() -> Document:
    return Document(
        document_id="doc", content="texte de test", tenant_id="alpha",
        visibility="private", owner_id="alice", allowed_groups=(),
        allowed_users=(), classification=1, doc_version=1,
        source_uri="local://doc",
    )


class TombstonePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = FakeQdrantClient()
        self.repository = QdrantChunkRepository(
            self.client, collection="chunks", embed=lambda _text: [1.0],
            lock_dir=self.temp.name,
        )
        self.document = _document()
        self.point = chunk_to_point(chunk_document(self.document)[0], [1.0])
        self.client.scroll_results = [self.point]
        self.client.stored_points = {self.point["id"]: self.point}

    def test_preflight_finds_ids_without_mutating_canonical_or_index(self):
        result = self.repository.inspect_tombstone_candidates(self.document)
        self.assertEqual(result, (self.point["id"],))
        self.assertEqual(self.client.deleted, [])
        self.assertEqual(self.client.upserted, [])
        self.assertIs(self.client.stored_points[self.point["id"]]["payload"]["tombstone"], False)

    def test_preflight_refuses_foreign_owner_on_late_page(self):
        foreign = {"id": str(uuid.UUID(int=(1 << 128) - 1)), "payload": {
            **self.point["payload"], "owner_id": "bob",
        }}
        self.client.scroll_results.append(foreign)
        self.client.stored_points[foreign["id"]] = foreign
        with patch.object(repository_module, "_OWNER_SCAN_PAGE_SIZE", 1):
            with self.assertRaises(PermissionError):
                self.repository.inspect_tombstone_candidates(self.document)
        self.assertEqual(len(self.client.scrolls), 2)
        self.assertEqual(self.client.deleted, [])
        self.assertEqual(self.client.upserted, [])

    def test_preflight_refuses_missing_or_non_uuid_points(self):
        self.client.stored_points.clear()
        with self.assertRaises(RuntimeError):
            self.repository.inspect_tombstone_candidates(self.document)
        self.client.scroll_results = [{**self.point, "id": 7}]
        self.client.stored_points[7] = self.client.scroll_results[0]
        with self.assertRaises(ValueError):
            self.repository.inspect_tombstone_candidates(self.document)
        self.assertEqual(self.client.deleted, [])
        self.assertEqual(self.client.upserted, [])

    def test_preflight_refuses_uuid_not_derived_from_point_identity(self):
        forged = {**self.point, "id": str(uuid.UUID(int=42))}
        self.client.scroll_results = [forged]
        self.client.stored_points = {forged["id"]: forged}
        with self.assertRaisesRegex(ValueError, "point identity"):
            self.repository.inspect_tombstone_candidates(self.document)

    def test_preflight_refuses_payload_divergent_from_current_document(self):
        for change in ({"doc_version": 999}, {"acl_version": 999},
                       {"text": "texte falsifié"}, {"allowed_user_ids": ["bob"]},
                       {"source_sha": "0" * 64}):
            with self.subTest(change=change):
                payload = {**self.point["payload"], **change}
                point = {**self.point, "payload": payload}
                self.client.scroll_results = [point]
                self.client.stored_points = {point["id"]: point}
                with self.assertRaises(ValueError):
                    self.repository.inspect_tombstone_candidates(self.document)

    def test_preflight_bounds_each_readback_batch(self):
        self.client.scroll_results = []
        self.client.stored_points = {}
        for index in range(257):
            payload = {**self.point["payload"], "chunk_id": f"chunk-{index}"}
            point_id = stable_point_id(
                tenant_id="alpha", document_id="doc", chunk_id=payload["chunk_id"],
                source_sha=payload["source_sha"], doc_version=payload["doc_version"],
            )
            point = {**self.point, "id": point_id, "payload": payload}
            self.client.scroll_results.append(point)
            self.client.stored_points[point["id"]] = point
        batches = []
        original = self.client.retrieve_points
        def bounded(collection, ids, *, with_vector=True):
            self.assertIs(with_vector, False)
            batches.append(len(ids))
            if len(ids) > 256:
                raise AssertionError("unbounded readback")
            return original(collection, ids)
        self.client.retrieve_points = bounded
        self.assertEqual(len(self.repository.inspect_tombstone_candidates(self.document)), 257)
        self.assertEqual(batches, [256, 1])

    def test_preflight_refuses_already_tombstoned_or_wrong_readback(self):
        self.client.stored_points[self.point["id"]] = {
            **self.point, "payload": {**self.point["payload"], "tombstone": True},
        }
        with self.assertRaises(ValueError):
            self.repository.inspect_tombstone_candidates(self.document)
        self.client.stored_points[self.point["id"]] = {
            **self.point, "payload": {**self.point["payload"], "owner_id": "bob"},
        }
        with self.assertRaises(PermissionError):
            self.repository.inspect_tombstone_candidates(self.document)
        self.assertEqual(self.client.deleted, [])
        self.assertEqual(self.client.upserted, [])
