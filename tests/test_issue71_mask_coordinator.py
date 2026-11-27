"""C0b: internal canonical-first mask coordination; no HTTP/service caller."""
from __future__ import annotations

from functools import partial
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from rag_hermes.canonical_registry import CanonicalDocumentRegistry
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_write_lock import DocumentWriteLockTimeout, document_write_lock
from rag_hermes.qdrant_store import chunk_to_point
from tests.test_qdrant_repository import FakeQdrantClient


class CanonicalTombstoneCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.registry = CanonicalDocumentRegistry(self.directory)
        self.document = Document(
            document_id="doc", content="alpha beta", tenant_id="alpha",
            visibility="private", owner_id="alice", allowed_groups=(),
            allowed_users=(), classification=1, doc_version=1,
            source_uri="local://doc",
        )
        self.registry.register(self.document)
        self.client = FakeQdrantClient()
        self.chunker = partial(chunk_document, max_tokens=1, overlap_tokens=0)
        self.points = [chunk_to_point(chunk, [1.0]) for chunk in self.chunker(self.document)]
        self.assertEqual(len(self.points), 2)
        self.client.scroll_results = list(self.points)
        self.client.stored_points = {point["id"]: point for point in self.points}
        self.repository = QdrantChunkRepository(
            self.client, collection="chunks", embed=lambda _: [1.0],
            lock_dir=self.directory, lock_timeout=0.1,
        )

    def test_divergent_index_is_refused_before_canonical_publication(self) -> None:
        from rag_hermes.canonical_tombstone import CanonicalTombstoneCoordinator

        point = self.points[0]
        self.client.stored_points[point["id"]] = {
            **point, "payload": {**point["payload"], "section": "forged"},
        }
        coordinator = CanonicalTombstoneCoordinator(
            self.registry, self.repository, chunker=self.chunker,
        )
        with self.assertRaisesRegex(ValueError, "canonical chunk manifest"):
            coordinator.mask_document(
                tenant_id="alpha", document_id="doc", owner_id="alice",
            )
        self.assertIsNotNone(self.registry.source("doc"))
        self.assertEqual(self.client.tombstoned, [])

    def test_cooperative_reader_waits_during_the_index_mark(self) -> None:
        from rag_hermes.canonical_tombstone import CanonicalTombstoneCoordinator

        reader_registry = CanonicalDocumentRegistry(self.directory)
        attempted = threading.Event()
        entered = threading.Event()
        thread: threading.Thread | None = None
        original_mark = self.client.mark_points_tombstoned
        def read_from_another_thread() -> None:
            attempted.set()
            with reader_registry.read_guard():
                entered.set()

        def mark_while_read_is_waiting(collection: str, ids: list[str]) -> None:
            nonlocal thread
            thread = threading.Thread(target=read_from_another_thread, daemon=True)
            thread.start()
            self.assertTrue(attempted.wait(3))
            self.assertFalse(entered.wait(0.25), "reader entered during the mask")
            original_mark(collection, ids)

        coordinator = CanonicalTombstoneCoordinator(
            self.registry, self.repository, chunker=self.chunker,
        )
        with patch.object(self.client, "mark_points_tombstoned", mark_while_read_is_waiting):
            self.assertEqual(coordinator.mask_document(
                tenant_id="alpha", document_id="doc", owner_id="alice",
            ), 2)
        self.assertIsNotNone(thread)
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(entered.is_set())

    def test_confirmation_failure_after_publication_is_an_index_reconciliation(self) -> None:
        from rag_hermes.canonical_tombstone import (
            CanonicalMaskIndexError, CanonicalTombstoneCoordinator,
        )

        coordinator = CanonicalTombstoneCoordinator(
            self.registry, self.repository, chunker=self.chunker,
        )
        # Canonical publication succeeds, but the post-publication confirmation
        # read is made to diverge. Since the document is already durably
        # inactive, this must surface as an INDEX reconciliation case, not a
        # pre-publication CanonicalStoreError a reconciliation tool would miss.
        real_manifest = self.registry.last_active_manifest
        def corrupt_manifest():
            _, inactive = real_manifest()
            return {}, inactive

        with patch.object(self.registry, "last_active_manifest", corrupt_manifest):
            with self.assertRaisesRegex(CanonicalMaskIndexError, "reconciliation"):
                coordinator.mask_document(
                    tenant_id="alpha", document_id="doc", owner_id="alice",
                )
        self.assertIsNone(self.registry.source("doc"))
        self.assertEqual(self.client.tombstoned, [])

    def test_second_scan_rejects_index_changed_after_canonical_publication(self) -> None:
        from rag_hermes.canonical_tombstone import (
            CanonicalMaskIndexError, CanonicalTombstoneCoordinator,
        )

        coordinator = CanonicalTombstoneCoordinator(
            self.registry, self.repository, chunker=self.chunker,
        )
        original_mask = self.registry.mark_inactive
        def alter_index_after_mask(document_id: str, *, owner_id: str):
            masked = original_mask(document_id, owner_id=owner_id)
            point = self.points[0]
            self.client.stored_points[point["id"]] = {
                **point, "payload": {**point["payload"], "section": "changed-after-mask"},
            }
            return masked

        with patch.object(self.registry, "mark_inactive", alter_index_after_mask):
            with self.assertRaisesRegex(CanonicalMaskIndexError, "reconciliation"):
                coordinator.mask_document(
                    tenant_id="alpha", document_id="doc", owner_id="alice",
                )
        self.assertIsNone(self.registry.source("doc"))
        self.assertEqual(self.client.tombstoned, [])

    def test_wrong_owner_cannot_publish_or_touch_index(self) -> None:
        from rag_hermes.canonical_tombstone import CanonicalTombstoneCoordinator

        coordinator = CanonicalTombstoneCoordinator(
            self.registry, self.repository, chunker=self.chunker,
        )
        for tenant, owner in (("alpha", "bob"), ("beta", "alice")):
            with self.subTest(tenant=tenant, owner=owner):
                with self.assertRaises(PermissionError):
                    coordinator.mask_document(
                        tenant_id=tenant, document_id="doc", owner_id=owner,
                    )
        self.assertEqual(self.registry.source("doc"), self.document)
        self.assertEqual(self.client.tombstoned, [])
        self.assertEqual(self.client.scrolls, [])

    def test_failed_canonical_publication_never_marks_the_index(self) -> None:
        from rag_hermes.canonical_tombstone import CanonicalTombstoneCoordinator

        coordinator = CanonicalTombstoneCoordinator(
            self.registry, self.repository, chunker=self.chunker,
        )
        with patch.object(self.registry, "_write_anchor", side_effect=OSError("test failure")):
            with self.assertRaises(OSError):
                coordinator.mask_document(
                    tenant_id="alpha", document_id="doc", owner_id="alice",
                )
        self.assertEqual(self.registry.source("doc"), self.document)
        self.assertEqual(self.client.tombstoned, [])

    def test_anchor_ahead_never_reports_a_mask_or_attempts_index_mark(self) -> None:
        from rag_hermes.canonical_registry import CanonicalStoreError
        from rag_hermes.canonical_tombstone import CanonicalTombstoneCoordinator

        coordinator = CanonicalTombstoneCoordinator(
            self.registry, self.repository, chunker=self.chunker,
        )
        original_anchor_write = self.registry._write_anchor
        def fail_after_anchor(*args, **kwargs):
            original_anchor_write(*args, **kwargs)
            raise OSError("simulated failure after anchor publication")

        with patch.object(self.registry, "_write_anchor", fail_after_anchor):
            with self.assertRaises(OSError):
                coordinator.mask_document(
                    tenant_id="alpha", document_id="doc", owner_id="alice",
                )
        self.assertEqual(self.client.tombstoned, [])
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.directory)

    def test_partial_index_mark_keeps_canonical_inactive_and_requires_reconciliation(self) -> None:
        from rag_hermes.canonical_tombstone import (
            CanonicalMaskIndexError, CanonicalTombstoneCoordinator,
        )

        coordinator = CanonicalTombstoneCoordinator(
            self.registry, self.repository, chunker=self.chunker,
        )
        def partial_mark(_collection: str, ids: list[str]) -> None:
            point = self.client.stored_points[ids[0]]
            self.client.stored_points[ids[0]] = {
                **point, "payload": {**point["payload"], "tombstone": True},
            }
            raise RuntimeError("simulated partial Qdrant write")

        with patch.object(self.client, "mark_points_tombstoned", partial_mark):
            with self.assertRaisesRegex(CanonicalMaskIndexError, "reconciliation"):
                coordinator.mask_document(
                    tenant_id="alpha", document_id="doc", owner_id="alice",
                )
        self.assertIsNone(CanonicalDocumentRegistry(self.directory).source("doc"))
        self.assertEqual(sorted(
            p["payload"]["tombstone"] for p in self.client.stored_points.values()
        ), [False, True])
        with self.assertRaisesRegex(ValueError, "already inactive"):
            coordinator.mask_document(
                tenant_id="alpha", document_id="doc", owner_id="alice",
            )

    def test_mask_publishes_inactive_before_index_write_and_confirms_all_points(self) -> None:
        from rag_hermes.canonical_tombstone import CanonicalTombstoneCoordinator

        coordinator = CanonicalTombstoneCoordinator(
            self.registry, self.repository, chunker=self.chunker,
        )
        original_mark = self.client.mark_points_tombstoned

        def check_canonical_then_mark(collection: str, ids: list[str]) -> None:
            self.assertIsNone(self.registry.source("doc"))
            last_active, masked = self.registry.last_active_manifest()
            self.assertEqual(last_active["doc"], self.document)
            self.assertIn("doc", masked)
            # A new descriptor cannot take the same document flock: the
            # coordinator has kept it since before canonical publication.
            with self.assertRaises(DocumentWriteLockTimeout):
                with document_write_lock(
                    self.directory, collection, "alpha", "doc", timeout=0,
                ):
                    self.fail("document lease was not held during the mark")
            original_mark(collection, ids)

        with patch.object(self.client, "mark_points_tombstoned", check_canonical_then_mark):
            self.assertEqual(coordinator.mask_document(
                tenant_id="alpha", document_id="doc", owner_id="alice",
            ), 2)
        self.assertIsNone(self.registry.source("doc"))
        self.assertIsNone(CanonicalDocumentRegistry(self.directory).source("doc"))
        self.assertEqual(len(self.client.tombstoned), 1)
        self.assertTrue(all(
            self.client.stored_points[point["id"]]["payload"]["tombstone"] is True
            for point in self.points
        ))
