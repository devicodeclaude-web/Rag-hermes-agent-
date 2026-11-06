"""CPU checks for a complete, externally supplied Qdrant point snapshot."""

import unittest
from copy import deepcopy

from rag_hermes.index_integrity import audit_qdrant_index, verify_index_snapshot
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_store import chunk_to_point


def document(document_id, text):
    return Document(
        document_id=document_id, content=text, tenant_id="alpha",
        visibility="private", owner_id="alice", allowed_groups=(),
        allowed_users=(), classification=1, doc_version=1,
        source_uri=f"file:///docs/{document_id}.md",
    )


class IndexSnapshotAuditTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [
            chunk_document(document("a", "Source A"))[0],
            chunk_document(document("b", "Source B"))[0],
        ]
        self.points = [chunk_to_point(chunk, [1.0]) for chunk in self.chunks]

    def test_complete_canonical_snapshot_passes(self):
        report = verify_index_snapshot(self.chunks, self.points)
        self.assertEqual(report.point_count, 2)
        self.assertEqual(len(report.payload_sha256), 64)
        self.assertEqual(report, verify_index_snapshot(self.chunks, list(reversed(self.points))))

    def test_restrictive_index_payload_hidden_by_prefilter_is_rejected(self):
        points = deepcopy(self.points)
        points[0]["payload"]["owner_id"] = "bob"
        with self.assertRaisesRegex(ValueError, "payload"):
            verify_index_snapshot(self.chunks, points)

    def test_missing_point_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            verify_index_snapshot(self.chunks, self.points[:1])

    def test_extra_point_is_rejected(self):
        extra = deepcopy(self.points[0])
        extra["id"] = "unexpected"
        with self.assertRaisesRegex(ValueError, "unexpected"):
            verify_index_snapshot(self.chunks, self.points + [extra])

    def test_duplicate_point_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            verify_index_snapshot(self.chunks, self.points + [self.points[0]])

    def test_complete_paginated_audit_uses_unfiltered_scroll(self):
        class FakeClient:
            def __init__(self, points):
                self.points = points
                self.calls = []

            def scroll_page(self, collection, *, limit, offset=None):
                self.calls.append((collection, limit, offset))
                start = 0 if offset is None else offset
                end = start + limit
                return self.points[start:end], end if end < len(self.points) else None

        client = FakeClient(self.points)
        report = audit_qdrant_index(client, "chunks", self.chunks, page_size=1)
        self.assertEqual(report.point_count, 2)
        self.assertEqual(client.calls, [("chunks", 1, None), ("chunks", 1, 1)])

    def test_paginated_audit_catches_hidden_restrictive_payload(self):
        forged = deepcopy(self.points)
        forged[0]["payload"]["owner_id"] = "bob"
        class FakeClient:
            def scroll_page(self, collection, *, limit, offset=None):
                return forged, None
        with self.assertRaisesRegex(ValueError, "payload"):
            audit_qdrant_index(FakeClient(), "chunks", self.chunks)

    def test_paginated_audit_rejects_repeated_cursor(self):
        points = self.points
        class FakeClient:
            def scroll_page(self, collection, *, limit, offset=None):
                return [points[0]], "same"
        with self.assertRaisesRegex(ValueError, "cursor"):
            audit_qdrant_index(FakeClient(), "chunks", self.chunks, page_size=1)

    def test_paginated_audit_rejects_missing_page(self):
        class FakeClient:
            def scroll_page(self, collection, *, limit, offset=None):
                return [], None
        with self.assertRaisesRegex(ValueError, "missing"):
            audit_qdrant_index(FakeClient(), "chunks", self.chunks)

    def test_boolean_integer_acl_type_tampering_is_rejected(self):
        for field, value in (
            ("classification", True),
            ("acl_version", True),
            ("doc_version", True),
            ("tombstone", 0),
        ):
            with self.subTest(field=field):
                points = deepcopy(self.points)
                points[0]["payload"][field] = value
                with self.assertRaisesRegex(ValueError, "payload"):
                    verify_index_snapshot(self.chunks, points)

    def test_payload_text_or_id_forgery_is_rejected(self):
        for field, value in (("text", "Secret B"), ("acl_version", 2)):
            with self.subTest(field=field):
                points = deepcopy(self.points)
                points[0]["payload"][field] = value
                with self.assertRaisesRegex(ValueError, "payload"):
                    verify_index_snapshot(self.chunks, points)
        points = deepcopy(self.points)
        points[0]["id"] = "forged"
        with self.assertRaisesRegex(ValueError, "missing"):
            verify_index_snapshot(self.chunks, points)
