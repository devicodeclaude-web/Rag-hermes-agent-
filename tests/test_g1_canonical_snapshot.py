"""Tests du registre documentaire épinglé hors Qdrant."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.canonical_snapshot import load_pinned_document_snapshot
from rag_hermes.ingestion import chunk_document
from rag_hermes.retrieval import CanonicalAclSearch, SearchResult
from rag_hermes.service import RagService


def record(identifier="a", text="Source canonique"):
    return {
        "document_id": identifier, "content": text, "tenant_id": "alpha",
        "visibility": "private", "owner_id": "alice", "allowed_groups": [],
        "allowed_users": [], "classification": 1, "doc_version": 1,
        "acl_version": 2, "source_uri": f"file:///docs/{identifier}.md",
    }


class PinnedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "documents.jsonl"

    def save(self, records):
        payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode()
        self.path.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    def test_pinned_snapshot_drives_source_and_authority(self):
        pinned = self.save([record()])
        snapshot = load_pinned_document_snapshot(self.path, expected_sha256=pinned)
        doc = snapshot.source("a")
        assert doc is not None
        self.assertEqual(doc.content, "Source canonique")
        self.assertEqual(snapshot.file_sha256, pinned)
        context = AuthorizationContext("alpha", "alice", (), 1)
        self.assertEqual(snapshot.authority().authorize("a", 2, context), (True, "allowed"))
        with self.assertRaises(TypeError):
            writable: Any = snapshot.documents
            writable["a"] = doc

    def test_pinned_snapshot_feeds_canonical_answer_path(self):
        pinned = self.save([record(text="Installez Hermes avec pipx")])
        snapshot = load_pinned_document_snapshot(self.path, expected_sha256=pinned)
        doc = snapshot.source("a")
        assert doc is not None

        class Ranked:
            def search(self, question, *, context, limit):
                return [SearchResult(chunk_document(doc)[0], 0.9)]

        bridge = CanonicalAclSearch(
            Ranked(), snapshot.authority(), source=snapshot.source,
        )
        service = RagService(
            repository=bridge, generator=lambda q, chunks: "Utilisez pipx [S1].",
        )
        context = AuthorizationContext("alpha", "alice", (), 1)
        trace = service.answer_with_trace("installer Hermes", context=context)
        self.assertFalse(trace.response.abstained)
        self.assertEqual(trace.response.citations[0].document_id, "a")

    def test_changed_bytes_rejected_before_parsing(self):
        pinned = self.save([record()])
        self.path.write_bytes(b"not json")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            load_pinned_document_snapshot(self.path, expected_sha256=pinned)

    def test_duplicate_ids_rejected(self):
        pinned = self.save([record(), record(text="Double")])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_pinned_document_snapshot(self.path, expected_sha256=pinned)

    def test_empty_snapshot_and_bad_pin_rejected(self):
        self.assertEqual(self.save([]), hashlib.sha256(b"").hexdigest())
        with self.assertRaisesRegex(ValueError, "empty"):
            load_pinned_document_snapshot(
                self.path, expected_sha256=hashlib.sha256(b"").hexdigest()
            )
        with self.assertRaisesRegex(ValueError, "invalid pinned"):
            load_pinned_document_snapshot(self.path, expected_sha256="bad")


if __name__ == "__main__":
    unittest.main()
