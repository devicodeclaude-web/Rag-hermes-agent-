"""Assemblage G1 : source indépendante, audit préalable, puis réponse citée."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.canonical_snapshot import load_pinned_document_snapshot
from rag_hermes.evaluation_runner import build_contextual_service_answer_fn, run_audited_evaluation
from rag_hermes.g1_wiring import build_audited_g1_service
from rag_hermes.index_integrity import (
    AuditedIndexSession, AuditedIndexSessionError, verify_index_snapshot,
)
from rag_hermes.ingestion import chunk_document
from rag_hermes.qdrant_store import chunk_to_point
from test_evaluation_runner import (
    DOC_CONTENT, _answerable_case, _documents, _manifest,
)


class G1WiringTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "docs.jsonl"
        path.write_text(json.dumps({
            "document_id": "a", "content": "Installez Hermes avec pipx",
            "tenant_id": "alpha", "visibility": "private", "owner_id": "alice",
            "allowed_groups": [], "allowed_users": [], "classification": 1,
            "doc_version": 1, "source_uri": "file:///docs/a.md",
        }) + "\n", encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.snapshot = load_pinned_document_snapshot(path, expected_sha256=digest)
        self.chunks = [chunk_document(doc)[0] for doc in self.snapshot.documents.values()]
        self.points = [chunk_to_point(chunk, [1.0]) for chunk in self.chunks]
        self.pin = verify_index_snapshot(self.chunks, self.points).payload_sha256

        class Audit:
            def __init__(self, points):
                self.points = points
                self.calls = 0
            def scroll_page(self, collection, *, limit, offset=None):
                self.calls += 1
                return self.points, None
        class Query:
            def __init__(self, points):
                self.points = points
                self.calls = 0
            def query(self, collection, vector, *, query_filter, limit):
                self.calls += 1
                return [{**p, "score": 0.9} for p in self.points][:limit]
        self.audit = Audit(self.points)
        self.query = Query(self.points)
        self.context = AuthorizationContext("alpha", "alice", (), 1)

    def build(self, *, pinned=None, query_client=None, audit_client=None):
        return build_audited_g1_service(
            snapshot=self.snapshot,
            expected_manifest_sha256=self.pin if pinned is None else pinned,
            audit_client=self.audit if audit_client is None else audit_client,
            query_client=self.query if query_client is None else query_client,
            collection="chunks", chunker=chunk_document,
            embed=lambda text: [1.0],
            generator=lambda q, chunks: "Utilisez pipx [S1].",
        )

    def test_audit_precedes_answer_and_only_canonical_chunk_is_cited(self):
        service, report = self.build()
        self.assertEqual((report.point_count, self.audit.calls, self.query.calls), (1, 1, 0))
        answer = service.answer("installer Hermes", context=self.context)
        self.assertEqual(answer.citations[0].document_id, "a")
        self.assertEqual(self.query.calls, 1)
        self.assertFalse(hasattr(service, "import_document"))

    def test_bad_pin_refuses_before_query_or_audit(self):
        with self.assertRaisesRegex(ValueError, "manifest digest"):
            self.build(pinned="0" * 64)
        self.assertEqual((self.audit.calls, self.query.calls), (0, 0))

    def test_tampered_index_refuses_before_query(self):
        self.audit.points = [{**self.points[0], "payload": {**self.points[0]["payload"], "owner_id": "bob"}}]
        with self.assertRaisesRegex(ValueError, "payload conflicts"):
            self.build()
        self.assertEqual(self.query.calls, 0)

    def test_merged_service_runs_the_audited_campaign_path(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "guide.jsonl"
            path.write_text(json.dumps({
                "document_id": "guide", "content": DOC_CONTENT,
                "tenant_id": "public", "visibility": "public", "owner_id": "system",
                "allowed_groups": [], "allowed_users": [], "classification": 0,
                "doc_version": 1, "source_uri": "synthetic://guide",
            }) + "\n", encoding="utf-8")
            snapshot = load_pinned_document_snapshot(
                path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            chunks = [chunk_document(doc)[0] for doc in snapshot.documents.values()]
            points = [chunk_to_point(chunk, [1.0]) for chunk in chunks]
            pinned = verify_index_snapshot(chunks, points).payload_sha256
            self.audit.points = points
            self.query.points = points
            service, _ = build_audited_g1_service(
                snapshot=snapshot, expected_manifest_sha256=pinned,
                audit_client=self.audit, query_client=self.query,
                collection="chunks", chunker=chunk_document, embed=lambda text: [1.0],
                generator=lambda question, evidence: "Installez avec pipx [S1].",
            )
            session = AuditedIndexSession(
                self.audit, "chunks", chunks, expected_manifest_sha256=pinned,
            )
            report = run_audited_evaluation(
                session, [_answerable_case()], _documents(), _manifest(),
                build_contextual_service_answer_fn(service), k=1,
                context_for_case=lambda case: AuthorizationContext("public", "evaluator", (), 0),
                authority=snapshot.authority(),
            )
            self.assertEqual(report.case_count, 1)
            self.assertEqual(report.recall_at_k, 1.0)
            self.assertTrue(report.security_gate_passed)
            self.assertEqual(self.audit.calls, 3)  # construction + ouverture + clôture
            self.assertEqual(self.query.calls, 1)

    def test_pinned_session_rejects_bad_pin_before_scroll(self):
        session = AuditedIndexSession(
            self.audit, "chunks", self.chunks, expected_manifest_sha256="0" * 64,
        )
        with self.assertRaises(AuditedIndexSessionError):
            session.open()
        self.assertEqual(self.audit.calls, 0)

    def test_pinned_session_rejects_post_answer_index_change(self):
        session = AuditedIndexSession(
            self.audit, "chunks", self.chunks, expected_manifest_sha256=self.pin,
        )
        session.open()
        service, _ = self.build()
        service.answer("installer Hermes", context=self.context)
        self.audit.points = [{**self.points[0], "payload": {**self.points[0]["payload"], "owner_id": "bob"}}]
        with self.assertRaises(AuditedIndexSessionError):
            session.close()

    def test_same_client_for_audit_and_query_is_refused(self):
        with self.assertRaisesRegex(ValueError, "separate"):
            self.build(query_client=self.audit)
        self.assertEqual(self.audit.calls, 0)


if __name__ == "__main__":
    unittest.main()
