"""CPU checks for a complete, externally supplied Qdrant point snapshot."""

import unittest
import threading
from copy import deepcopy

from rag_hermes.index_integrity import (
    AuditedIndexSession,
    AuditedIndexSessionError,
    audit_qdrant_index,
    verify_index_snapshot,
)
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

    def test_concurrent_close_cannot_run_a_second_audit(self):
        points = self.points
        for _ in range(100):
            audits = []

            class CountingClient:
                def scroll_page(self, collection, *, limit, offset=None):
                    audits.append(offset)
                    return points, None

            session = AuditedIndexSession(CountingClient(), "chunks", self.chunks)
            session.open()
            audits.clear()
            outcomes = []

            def run():
                try:
                    outcomes.append(("ok", session.close()))
                except Exception as exc:  # noqa: BLE001 - recording the gate
                    outcomes.append(("err", exc))

            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            # Exactly one closing audit, and exactly one caller gets a report.
            self.assertEqual(len(audits), 1)
            self.assertEqual(len([o for o in outcomes if o[0] == "ok"]), 1)
            losers = [o[1] for o in outcomes if o[0] == "err"]
            self.assertEqual(len(losers), 1)
            self.assertIsInstance(losers[0], ValueError)

    def test_invalidate_during_opening_cannot_resurrect_the_session(self):
        started = threading.Event()
        release = threading.Event()
        outcomes = []
        points = self.points

        class PausedClient:
            def scroll_page(self, collection, *, limit, offset=None):
                started.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("opening audit did not resume")
                return points, None

        session = AuditedIndexSession(PausedClient(), "chunks", self.chunks)

        def open_session():
            try:
                outcomes.append(("ok", session.open()))
            except Exception as exc:
                outcomes.append(("err", exc))

        worker = threading.Thread(target=open_session)
        worker.start()
        try:
            self.assertTrue(started.wait(timeout=5))
            session.invalidate()
        finally:
            release.set()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0][0], "err")
        with self.assertRaises(ValueError):
            session.open()
        with self.assertRaises(ValueError):
            session.close()

    def test_invalidate_during_closing_cannot_return_a_report(self):
        started = threading.Event()
        release = threading.Event()
        outcomes = []
        points = self.points
        calls = 0

        class PausedClient:
            def scroll_page(self, collection, *, limit, offset=None):
                nonlocal calls
                calls += 1
                if calls == 2:
                    started.set()
                    if not release.wait(timeout=5):
                        raise TimeoutError("closing audit did not resume")
                return points, None

        session = AuditedIndexSession(PausedClient(), "chunks", self.chunks)
        session.open()

        def close_session():
            try:
                outcomes.append(("ok", session.close()))
            except Exception as exc:
                outcomes.append(("err", exc))

        worker = threading.Thread(target=close_session)
        worker.start()
        try:
            self.assertTrue(started.wait(timeout=5))
            session.invalidate()
        finally:
            release.set()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(calls, 2)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0][0], "err")
        with self.assertRaises(ValueError):
            session.close()

    def test_state_is_terminal_before_the_audit_runs(self):
        points = self.points
        observed = []

        class ReentrantClient:
            def __init__(self):
                self.session = None

            def scroll_page(self, collection, *, limit, offset=None):
                try:
                    self.session.close()
                except Exception as exc:  # noqa: BLE001 - recording the gate
                    observed.append(exc)
                return points, None

        client = ReentrantClient()
        session = AuditedIndexSession(client, "chunks", self.chunks)
        client.session = session
        session.open()
        session.close()
        # The gate must already be closed while the audit is in flight, so a
        # concurrent or re-entrant caller can never start a second audit.
        self.assertTrue(observed)
        for exc in observed:
            self.assertIsInstance(exc, ValueError)
            self.assertRegex(str(exc), "finished|not opened")

    def test_audit_failure_message_does_not_echo_the_cause(self):
        # Stands in for anything sensitive a transport error may carry (URL,
        # credentials, response body). Deliberately not credential-shaped, so
        # the repository's secret scanner has nothing to flag.
        marker = "CAUSE-DETAIL-MUST-NOT-LEAK"
        pages = [self.points]

        class FakeClient:
            def scroll_page(self, collection, *, limit, offset=None):
                if pages:
                    return pages.pop(0), None
                raise RuntimeError(f"Qdrant unavailable: {marker}")

        session = AuditedIndexSession(FakeClient(), "chunks", self.chunks)
        session.open()
        with self.assertRaises(AuditedIndexSessionError) as caught:
            session.close()
        self.assertNotIn(marker, str(caught.exception))
        self.assertEqual(str(caught.exception), "closing audit failed")
        self.assertIn(marker, str(caught.exception.__cause__))

    def test_failed_close_cannot_be_retried_into_a_pass(self):
        mutated = deepcopy(self.points)
        mutated[0]["payload"]["owner_id"] = "bob"
        pages = [self.points, mutated, self.points]

        class FakeClient:
            def scroll_page(self, collection, *, limit, offset=None):
                return pages.pop(0), None

        session = AuditedIndexSession(FakeClient(), "chunks", self.chunks)
        session.open()
        with self.assertRaises(AuditedIndexSessionError):
            session.close()
        with self.assertRaisesRegex(ValueError, "finished"):
            session.close()
        with self.assertRaisesRegex(ValueError, "already opened"):
            session.open()

    def test_protocol_fault_at_close_is_not_reported_as_index_mutation(self):
        pages = [self.points]

        class FakeClient:
            def scroll_page(self, collection, *, limit, offset=None):
                if pages:
                    return pages.pop(0), None
                raise RuntimeError("Qdrant unavailable: connection refused")

        session = AuditedIndexSession(FakeClient(), "chunks", self.chunks)
        session.open()
        with self.assertRaises(AuditedIndexSessionError) as caught:
            session.close()
        message = str(caught.exception)
        self.assertIn("closing audit failed", message)
        self.assertNotIn("mutated", message)

    def test_session_refuses_invalid_collection_or_manifest_at_construction(self):
        class FakeClient:
            def scroll_page(self, collection, *, limit, offset=None):
                raise AssertionError("no audit expected")

        with self.assertRaisesRegex(ValueError, "collection"):
            AuditedIndexSession(FakeClient(), "", self.chunks)
        with self.assertRaisesRegex(ValueError, "page_size"):
            AuditedIndexSession(FakeClient(), "chunks", self.chunks, page_size=0)
        with self.assertRaisesRegex(ValueError, "empty canonical chunk manifest"):
            AuditedIndexSession(FakeClient(), "chunks", [])

    def test_reaudit_after_campaign_detects_index_mutation(self):
        mutated = deepcopy(self.points)
        mutated[0]["payload"]["owner_id"] = "bob"
        pages = [self.points, mutated]

        class FakeClient:
            def scroll_page(self, collection, *, limit, offset=None):
                return pages.pop(0), None

        session = AuditedIndexSession(FakeClient(), "chunks", self.chunks)
        opening = session.open()
        self.assertEqual(opening.point_count, 2)
        with self.assertRaisesRegex(AuditedIndexSessionError, "closing audit failed"):
            session.close()

    def test_reaudit_after_campaign_accepts_unchanged_index(self):
        pages = [self.points, list(reversed(self.points))]

        class FakeClient:
            def scroll_page(self, collection, *, limit, offset=None):
                return pages.pop(0), None

        session = AuditedIndexSession(FakeClient(), "chunks", self.chunks)
        opening = session.open()
        closing = session.close()
        # Both reports derive from the same manifest, so equality is expected and
        # proves nothing by itself; the evidence is that the closing audit re-ran.
        self.assertEqual(opening, closing)

    def test_session_refuses_close_before_open_and_double_open(self):
        points = self.points

        class FakeClient:
            def scroll_page(self, collection, *, limit, offset=None):
                return points, None

        session = AuditedIndexSession(FakeClient(), "chunks", self.chunks)
        with self.assertRaisesRegex(ValueError, "not opened"):
            session.close()
        session.open()
        with self.assertRaisesRegex(ValueError, "already opened"):
            session.open()
        session.close()
        with self.assertRaisesRegex(ValueError, "finished"):
            session.close()

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
