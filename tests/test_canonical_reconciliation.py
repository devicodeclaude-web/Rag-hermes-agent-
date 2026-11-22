"""Diagnostic hors ligne SEC-02 : jamais une réparation ni un feu vert de service."""
from __future__ import annotations

import hashlib
from dataclasses import replace
import errno
from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rag_hermes.canonical_registry import CanonicalDocumentRegistry
from rag_hermes.canonical_reconciliation import audit_canonical_copy_index
from rag_hermes.index_integrity import IndexSnapshotReport
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_store import chunk_to_point


def _document(*, version: int = 1, users: tuple[str, ...] = ("bob",)) -> Document:
    return Document(
        document_id="doc-1", content="texte confidentiel de contrôle",
        tenant_id="alpha", visibility="private", owner_id="alice",
        allowed_groups=(), allowed_users=users, classification=1,
        doc_version=1, acl_version=version, source_uri="file:///doc-1",
    )


class _PagedAuditClient:
    def __init__(self, points):
        self.points = points
        self.calls = []

    def scroll_page(self, collection, *, limit, offset=None):
        self.calls.append((collection, limit, offset))
        start = 0 if offset is None else offset
        end = start + limit
        return self.points[start:end], (end if end < len(self.points) else None)


class CanonicalReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name)
        self.registry = CanonicalDocumentRegistry(self.store)
        self.registry.register(_document())
        self.anchor_digest = hashlib.sha256(self.registry.anchor_path.read_bytes()).hexdigest()
        self.points = [chunk_to_point(chunk, [1.0]) for chunk in chunk_document(_document())]
        self.client = _PagedAuditClient(self.points)

    def audit(self, **kwargs):
        return audit_canonical_copy_index(
            self.store, anchor_sha256=self.anchor_digest,
            client=self.client, collection="chunks", chunker=chunk_document,
            page_size=1, **kwargs,
        )

    def test_matching_copy_is_audited_read_only(self):
        before = {p.name: p.read_bytes() for p in self.store.iterdir()}
        report = self.audit()
        self.assertIsInstance(report, IndexSnapshotReport)
        self.assertEqual(report.point_count, len(self.points))
        self.assertEqual({p.name: p.read_bytes() for p in self.store.iterdir()}, before)
        self.assertEqual(self.client.calls, [("chunks", 1, None)])

    def test_missing_indexed_point_is_refused_not_called_repaired(self):
        self.client.points = []
        with self.assertRaisesRegex(ValueError, "missing canonical indexed points"):
            self.audit()
        self.assertEqual(self.client.calls, [("chunks", 1, None)])

    def test_anchor_pin_mismatch_refuses_before_qdrant(self):
        self.anchor_digest = "0" * 64
        with self.assertRaisesRegex(ValueError, "anchor.*digest"):
            self.audit()
        self.assertEqual(self.client.calls, [])

    def test_missing_lock_is_not_recreated(self):
        (self.store / "canonical_transaction.lock").unlink()
        with self.assertRaises(FileNotFoundError):
            self.audit()
        self.assertFalse((self.store / "canonical_transaction.lock").exists())
        self.assertEqual(self.client.calls, [])

    def test_audit_never_opens_the_copy_for_writing(self):
        """Pins the doc claim: usable on read-only media, creates nothing."""
        real_open = os.open
        refused = []
        def readonly_open(path, flags, *args, **kwargs):
            if flags & (os.O_ACCMODE | os.O_CREAT) != os.O_RDONLY:
                refused.append(path)
                raise OSError(errno.EROFS, "read-only media")
            return real_open(path, flags, *args, **kwargs)
        with patch("rag_hermes.canonical_registry.os.open", readonly_open):
            self.assertEqual(self.audit().point_count, 1)
        self.assertEqual(refused, [])
        self.assertEqual(
            sorted(p.name for p in self.store.iterdir()),
            ["canonical_anchor.json", "canonical_documents.jsonl",
             "canonical_transaction.lock"],
        )

    def test_revised_acl_with_stale_index_is_detected(self):
        self.registry.register(_document(version=2, users=()))
        self.anchor_digest = hashlib.sha256(self.registry.anchor_path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "indexed payload conflicts"):
            self.audit()

    def test_unanchored_copy_is_refused_before_qdrant(self):
        self.registry.anchor_path.unlink()
        with self.assertRaisesRegex(Exception, "anchor"):
            self.audit()
        self.assertEqual(self.client.calls, [])

    def test_a_document_without_chunks_cannot_disappear_from_the_audit(self):
        self.registry.register(replace(_document(), document_id="doc-empty", content="   "))
        self.anchor_digest = hashlib.sha256(self.registry.anchor_path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "canonical document produced no chunks"):
            self.audit()
        self.assertEqual(self.client.calls, [])

    def test_copy_changed_during_scroll_never_returns_a_report(self):
        original = self.client.scroll_page
        def mutate(collection, *, limit, offset=None):
            page = original(collection, limit=limit, offset=offset)
            self.registry.anchor_path.unlink()
            return page
        self.client.scroll_page = mutate
        with self.assertRaises(FileNotFoundError):
            self.audit()
        self.assertEqual(self.client.calls, [("chunks", 1, None)])

    def test_cli_requires_read_only_token_before_network(self):
        from scripts import audit_canonical_copy as command
        args = ["audit_canonical_copy.py", "--copy", str(self.store),
                "--anchor-sha256", self.anchor_digest, "--qdrant-url", "http://localhost:6333",
                "--collection", "chunks", "--tokenizer-lock", "lock.json",
                "--tokenizer-file", "tokenizer.json"]
        with (patch("sys.argv", args), patch.dict(os.environ, {}, clear=True),
              patch.object(command, "QdrantAuditClient") as audit_client,
              patch("sys.stdout", new_callable=StringIO) as output):
            self.assertNotEqual(command.main(), 0)
        audit_client.assert_not_called()
        self.assertIn("REFUS", output.getvalue())
