"""Lecture seule préalable au marquage #71 ; ce plan n'autorise aucune mutation."""
from __future__ import annotations

from dataclasses import replace
from functools import partial
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

    def test_canonical_inventory_requires_every_expected_chunk(self):
        doc = replace(self.document, content="alpha beta")
        chunker = partial(chunk_document, max_tokens=1, overlap_tokens=0)
        chunks = chunker(doc)
        self.assertEqual(len(chunks), 2)
        first = chunk_to_point(chunks[0], [1.0])
        self.client.scroll_results = [first]
        self.client.stored_points = {first["id"]: first}
        with self.assertRaisesRegex(ValueError, "canonical chunk manifest"):
            self.repository.inspect_canonical_tombstone_candidates(doc, chunker=chunker)

    def test_canonical_inventory_accepts_all_expected_chunks(self):
        doc = replace(self.document, content="alpha beta")
        chunker = partial(chunk_document, max_tokens=1, overlap_tokens=0)
        points = [chunk_to_point(chunk, [1.0]) for chunk in chunker(doc)]
        self.client.scroll_results = points
        self.client.stored_points = {point["id"]: point for point in points}
        self.assertEqual(
            self.repository.inspect_canonical_tombstone_candidates(doc, chunker=chunker),
            tuple(sorted(point["id"] for point in points)),
        )
        self.assertEqual(self.client.deleted, [])
        self.assertEqual(self.client.upserted, [])

    def test_canonical_inventory_bounds_lazy_manifest_consumption(self):
        generated = []
        source = chunk_document(self.document)[0]
        def lazy_chunker(_document):
            for index in range(100):
                generated.append(index)
                yield replace(source, chunk_id=f"chunk-{index}")
        with patch.object(repository_module, "_OWNER_SCAN_BUDGET", 2):
            with self.assertRaisesRegex(ValueError, "exceeds scan budget"):
                self.repository.inspect_canonical_tombstone_candidates(
                    self.document, chunker=lazy_chunker,
                )
        self.assertEqual(generated, [0, 1, 2])
        self.assertEqual(self.client.scrolls, [])

    def test_canonical_inventory_rejects_forged_chunk_identity_and_payload(self):
        payload = {**self.point["payload"], "chunk_id": "invented-chunk"}
        forged_id = stable_point_id(
            tenant_id=payload["tenant_id"], document_id=payload["document_id"],
            chunk_id=payload["chunk_id"], source_sha=payload["source_sha"],
            doc_version=payload["doc_version"],
        )
        forged = {**self.point, "id": forged_id, "payload": payload}
        self.client.scroll_results = [forged]
        self.client.stored_points = {forged_id: forged}
        # The older index-only diagnostic intentionally accepts self-consistency.
        self.assertEqual(self.repository.inspect_tombstone_candidates(self.document), (forged_id,))
        with self.assertRaisesRegex(ValueError, "canonical chunk manifest"):
            self.repository.inspect_canonical_tombstone_candidates(
                self.document, chunker=chunk_document,
            )
        for change in ({"section": "invented"}, {"token_count": 999}):
            with self.subTest(change=change):
                changed = {**self.point, "payload": {**self.point["payload"], **change}}
                self.client.scroll_results = [changed]
                self.client.stored_points = {self.point["id"]: changed}
                with self.assertRaisesRegex(ValueError, "canonical chunk manifest"):
                    self.repository.inspect_canonical_tombstone_candidates(
                        self.document, chunker=chunk_document,
                    )

    def test_canonical_inventory_rejects_unexpected_extra_point(self):
        doc = replace(self.document, content="alpha beta")
        chunks = chunk_document(doc, max_tokens=1, overlap_tokens=0)
        points = [chunk_to_point(chunk, [1.0]) for chunk in chunks]
        self.client.scroll_results = points
        self.client.stored_points = {point["id"]: point for point in points}
        with self.assertRaisesRegex(ValueError, "canonical chunk manifest"):
            self.repository.inspect_canonical_tombstone_candidates(
                doc, chunker=lambda _document: chunks[:1],
            )

    def test_canonical_inventory_rejects_missing_or_duplicate_manifest(self):
        with self.assertRaisesRegex(ValueError, "canonical chunk manifest is empty"):
            self.repository.inspect_canonical_tombstone_candidates(
                self.document, chunker=lambda _document: [],
            )
        with self.assertRaisesRegex(ValueError, "duplicate ids"):
            self.repository.inspect_canonical_tombstone_candidates(
                self.document, chunker=lambda _document: chunk_document(self.document) * 2,
            )
        with self.assertRaisesRegex(ValueError, "approved chunker"):
            self.repository.inspect_canonical_tombstone_candidates(
                self.document, chunker=None,
            )

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


class ApplyDocumentTombstoneTests(unittest.TestCase):
    """The first real index mutation of the masking flow: scan+mark+reread."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = FakeQdrantClient()
        self.repository = QdrantChunkRepository(
            self.client, collection="chunks", embed=lambda _text: [1.0],
            lock_dir=self.temp.name,
        )
        # The document whose index points still carry the pre-masking payload.
        self.document = replace(_document(), content="alpha beta")
        self.chunker = partial(chunk_document, max_tokens=1, overlap_tokens=0)
        self.chunks = self.chunker(self.document)
        self.assertEqual(len(self.chunks), 2)
        self.points = [chunk_to_point(chunk, [1.0]) for chunk in self.chunks]
        self.client.scroll_results = list(self.points)
        self.client.stored_points = {point["id"]: point for point in self.points}

    def _ids(self):
        return sorted(point["id"] for point in self.points)

    def test_apply_marks_every_point_and_confirms_via_readback(self):
        count = self.repository.apply_document_tombstone(self.document, chunker=self.chunker)
        self.assertEqual(count, 2)
        self.assertEqual(self.client.tombstoned, [("chunks", self._ids())])
        for point_id in self._ids():
            self.assertIs(self.client.stored_points[point_id]["payload"]["tombstone"], True)
        self.assertEqual(self.client.deleted, [])
        self.assertEqual(self.client.upserted, [])

    def test_apply_requires_an_approved_chunker(self):
        with self.assertRaisesRegex(ValueError, "approved chunker"):
            self.repository.apply_document_tombstone(self.document, chunker=None)
        self.assertEqual(self.client.tombstoned, [])

    def test_apply_requires_the_last_active_document(self):
        with self.assertRaisesRegex(ValueError, "active canonical Document"):
            self.repository.apply_document_tombstone(
                replace(self.document, state="inactive"), chunker=self.chunker,
            )
        self.assertEqual(self.client.tombstoned, [])

    def test_apply_fails_closed_when_the_server_refuses_the_mark(self):
        self.client.fail_mark = True
        with self.assertRaises(RuntimeError):
            self.repository.apply_document_tombstone(self.document, chunker=self.chunker)
        # The scan proved the ids before the refusal; the mark was attempted.
        self.assertEqual(self.client.tombstoned, [("chunks", self._ids())])

    def test_apply_fails_closed_when_the_tombstone_did_not_take(self):
        # The mark call "succeeds" but the flag never flips (lost/ambiguous write).
        self.client.mark_applies = False
        with self.assertRaisesRegex(RuntimeError, "reconciliation"):
            self.repository.apply_document_tombstone(self.document, chunker=self.chunker)
        self.assertEqual(self.client.tombstoned, [("chunks", self._ids())])
        for point_id in self._ids():
            self.assertIs(self.client.stored_points[point_id]["payload"]["tombstone"], False)

    def test_apply_refuses_a_manifest_mismatch_without_marking(self):
        extra = chunk_to_point(
            replace(self.chunks[0], chunk_id="forged"), [1.0],
        )
        self.client.scroll_results.append(extra)
        self.client.stored_points[extra["id"]] = extra
        with self.assertRaisesRegex(ValueError, "canonical chunk manifest"):
            self.repository.apply_document_tombstone(self.document, chunker=self.chunker)
        self.assertEqual(self.client.tombstoned, [])

    def test_apply_refuses_an_already_tombstoned_point_without_marking(self):
        first = self._ids()[0]
        self.client.stored_points[first] = {
            **self.client.stored_points[first],
            "payload": {**self.client.stored_points[first]["payload"], "tombstone": True},
        }
        with self.assertRaises(ValueError):
            self.repository.apply_document_tombstone(self.document, chunker=self.chunker)
        self.assertEqual(self.client.tombstoned, [])
