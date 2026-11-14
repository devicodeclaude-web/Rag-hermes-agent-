"""Fenêtre candidate-only auditée, sans génération ni abstention."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rag_hermes.acl import AuthorizationContext
from rag_hermes.index_integrity import AuditedIndexSessionError, verify_index_snapshot
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_preflight import REQUIRED_PAYLOAD_INDEXES
from rag_hermes.qdrant_store import chunk_to_point


class FakeAuditClient:
    def __init__(self, points, events):
        self.points = points
        self.events = events
    def scroll_page(self, collection, *, limit, offset=None):
        self.events.append(("audit", collection, offset))
        return self.points, None


class FakeQueryClient:
    def __init__(self, points, events):
        self.points = points
        self.events = events
        self.fail = False
        self.schema_ready = True
    def get_collection(self, collection):
        self.events.append(("schema", collection))
        return {
            "config": {"params": {
                "vectors": {"dense": {"size": 2, "distance": "Cosine"}},
                "sparse_vectors": {"sparse": {}} if self.schema_ready else {},
            }},
            "payload_schema": {
                field: {"data_type": required.data_type,
                        "params": {"is_tenant": required.is_tenant}}
                for field, required in REQUIRED_PAYLOAD_INDEXES.items()
            },
        }
    def query(self, collection, vector, *, query_filter, limit):
        self.events.append(("dense", collection, limit))
        if self.fail:
            raise RuntimeError("query unavailable")
        return [{**point, "score": 0.9} for point in self.points][:limit]
    def query_sparse(self, collection, weights, *, context, limit):
        self.events.append(("sparse", collection, limit))
        return []


class FakeTokenizer:
    def __call__(self, query, passage, **kwargs):
        return {"input_ids": [1, 2]}


class FakeReranker:
    def __init__(self, events, on_score=None):
        self.events, self.on_score = events, on_score
    def compute_score(self, pairs, **kwargs):
        self.events.append(("rerank", len(pairs), kwargs["max_length"]))
        if self.on_score is not None:
            self.on_score()
        return [0.6 for _ in pairs]


class AuditedG1CandidateWindowTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "documents.jsonl"
        self.document = Document(
            document_id="guide", content="Installez Hermes avec pipx.",
            tenant_id="alpha", visibility="private", owner_id="alice",
            allowed_groups=(), allowed_users=(), classification=1,
            doc_version=1, source_uri="local://guide",
        )
        self.path.write_text(json.dumps(asdict(self.document)) + "\n", encoding="utf-8")
        self.source_sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.context = AuthorizationContext("alpha", "alice", (), 1)
        self.chunks = chunk_document(self.document)
        self.points = [chunk_to_point(chunk, [1.0, 0.0]) for chunk in self.chunks]
        self.manifest_sha = verify_index_snapshot(self.chunks, self.points).payload_sha256
        self.events = []
        self.audit = FakeAuditClient(self.points, self.events)
        self.query = FakeQueryClient(self.points, self.events)
        self.model = FakeReranker(self.events)
        self.urls = []

    def reset_document(self, document, context):
        self.document, self.context = document, context
        self.path.write_text(json.dumps(asdict(document)) + "\n", encoding="utf-8")
        self.source_sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.chunks = chunk_document(document)
        self.points = [chunk_to_point(chunk, [1.0, 0.0]) for chunk in self.chunks]
        self.manifest_sha = verify_index_snapshot(self.chunks, self.points).payload_sha256
        self.audit.points = self.points
        self.query.points = self.points

    def run_window(self, **overrides):
        from rag_hermes.g1_audited_candidates import run_audited_g1_candidate_window
        def make_audit(url):
            self.urls.append(("audit", url))
            return self.audit
        def make_query(url):
            self.urls.append(("query", url))
            return self.query
        parameters = dict(
            base_url="http://localhost:6333", collection="audited_chunks",
            source_path=self.path, expected_source_sha256=self.source_sha,
            expected_manifest_sha256=self.manifest_sha,
            chunker=chunk_document,
            embed_hybrid=lambda question: ([1.0, 0.0], {"7": 0.5}),
            reranker=self.model, tokenizer=FakeTokenizer(),
            question="comment installer ?", context=self.context,
        )
        parameters.update(overrides)
        with patch("rag_hermes.g1_audited_candidates.QdrantAuditRestClient", side_effect=make_audit), patch(
            "rag_hermes.g1_audited_candidates.QdrantRestClient", side_effect=make_query
        ):
            return run_audited_g1_candidate_window(**parameters)

    def test_both_audits_bracket_hybrid_query_and_reranking_on_one_collection(self):
        window = self.run_window()
        self.assertEqual([item.chunk.document_id for item in window.candidates], ["guide"])
        self.assertEqual(window.opening.point_count, 1)
        self.assertEqual(window.closing.point_count, 1)
        self.assertEqual(self.urls, [
            ("audit", "http://localhost:6333"),
            ("query", "http://localhost:6333"),
        ])
        self.assertEqual(self.events, [
            ("schema", "audited_chunks"),
            ("audit", "audited_chunks", None),
            ("dense", "audited_chunks", 40),
            ("sparse", "audited_chunks", 40),
            ("rerank", 1, 512),
            ("audit", "audited_chunks", None),
        ])
        self.assertFalse(hasattr(window, "abstained"))
        self.assertFalse(hasattr(window, "answer"))

    def test_global_public_document_is_allowed_for_private_tenant_caller(self):
        self.reset_document(
            replace(self.document, tenant_id="public", visibility="public",
                    owner_id="system", classification=0),
            self.context,
        )
        window = self.run_window()
        self.assertEqual([item.chunk.document_id for item in window.candidates], ["guide"])
        self.assertEqual([event[0] for event in self.events][-1], "audit")

    def test_group_permission_is_allowed_for_non_owner(self):
        self.reset_document(
            replace(self.document, owner_id="bob", allowed_groups=("support",)),
            AuthorizationContext("alpha", "alice", ("support",), 1),
        )
        window = self.run_window()
        self.assertEqual([item.chunk.document_id for item in window.candidates], ["guide"])
        self.assertEqual([event[0] for event in self.events][-1], "audit")

    def test_allowed_users_permission_is_allowed_for_non_owner(self):
        self.reset_document(
            replace(self.document, owner_id="bob", allowed_users=("alice",)),
            self.context,
        )
        window = self.run_window()
        self.assertEqual([item.chunk.document_id for item in window.candidates], ["guide"])
        self.assertEqual([event[0] for event in self.events][-1], "audit")

    def test_missing_sparse_schema_fails_before_any_scroll_or_query(self):
        from rag_hermes.qdrant_preflight import QdrantPreflightError
        self.query.schema_ready = False
        with self.assertRaises(QdrantPreflightError):
            self.run_window()
        self.assertEqual(self.events, [("schema", "audited_chunks")])

    def test_index_divergence_at_open_blocks_retrieval_and_reranking(self):
        self.audit.points = [{**self.points[0], "payload": {
            **self.points[0]["payload"], "owner_id": "bob",
        }}]
        with self.assertRaisesRegex(AuditedIndexSessionError, "opening audit failed"):
            self.run_window()
        self.assertEqual([event[0] for event in self.events], ["schema", "audit"])

    def test_bad_manifest_pin_refuses_before_any_query_or_scroll(self):
        with self.assertRaises(AuditedIndexSessionError):
            self.run_window(expected_manifest_sha256="0" * 64)
        self.assertEqual(self.events, [("schema", "audited_chunks")])

    def test_bad_source_digest_refuses_before_any_query_or_scroll(self):
        with self.assertRaises(ValueError):
            self.run_window(expected_source_sha256="0" * 64)
        self.assertEqual(self.events, [])

    def test_query_hit_not_in_audited_manifest_fails_before_model(self):
        # Même document/ACL/texte mais point et chunk_id INVENTÉS par query.
        forged = replace(self.chunks[0], chunk_id="forged-chunk-id")
        self.query.points = [chunk_to_point(forged, [1.0, 0.0])]
        with self.assertRaisesRegex(PermissionError, "audited manifest"):
            self.run_window()
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse",
        ])

    def test_query_hit_with_same_id_but_forged_payload_fails_before_model(self):
        forged = replace(self.chunks[0], token_count=self.chunks[0].token_count + 1)
        self.query.points = [chunk_to_point(forged, [1.0, 0.0])]
        self.assertEqual(self.query.points[0]["id"], self.points[0]["id"])
        with self.assertRaisesRegex(PermissionError, "audited manifest"):
            self.run_window()
        self.assertNotIn("rerank", [event[0] for event in self.events])

    def test_changed_index_at_close_discards_reranked_window(self):
        def tamper():
            self.audit.points = [{**self.points[0], "payload": {
                **self.points[0]["payload"], "owner_id": "bob",
            }}]
        self.model.on_score = tamper
        with self.assertRaisesRegex(AuditedIndexSessionError, "closing audit failed"):
            self.run_window()
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse", "rerank", "audit",
        ])

    def test_query_error_aborts_without_a_closing_audit(self):
        self.query.fail = True
        with self.assertRaisesRegex(RuntimeError, "query unavailable"):
            self.run_window()
        self.assertEqual([event[0] for event in self.events], ["schema", "audit", "dense"])

    def test_empty_window_still_audits_both_sides_without_calling_model(self):
        self.query.points = []
        window = self.run_window()
        self.assertEqual(window.candidates, ())
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse", "audit",
        ])


if __name__ == "__main__":
    unittest.main()
