"""Offline replay of versioned ingestion evidence; never a Qdrant writer."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from rag_hermes.canonical_registry import (
    CanonicalDocumentRegistry, CanonicalStoreError, bootstrap_canonical_anchor,
    verify_anchor_recovery_candidate,
)
from rag_hermes.ingestion import Document, chunk_document_tokens
from rag_hermes.qdrant_store import chunk_to_point


def document() -> Document:
    return Document(
        document_id="doc-1", content="one two three", tenant_id="alpha",
        visibility="private", owner_id="alice", allowed_groups=(), allowed_users=(),
        classification=1, doc_version=1, source_uri="file:///docs/doc-1.md", acl_version=1,
    )


class TinyTokenizer:
    def __call__(self, text, **kwargs):
        words = text.split()
        offsets = []
        pos = 0
        for word in words:
            start = text.index(word, pos)
            offsets.append((start, start + len(word)))
            pos = start + len(word)
        return {"input_ids": list(range(len(words))), "offset_mapping": offsets}


def intent(document_line: str, *, index: int = 1) -> dict:
    doc = document()
    chunks = chunk_document_tokens(
        doc, TinyTokenizer(), max_passage_tokens=10, overlap_tokens=0,
        tokenizer_name="BAAI/bge-reranker-v2-m3", tokenizer_revision="a" * 40,
    )
    points = [chunk_to_point(chunk, [1.0]) for chunk in chunks]
    return {
        "event_version": 1, "kind": "ingestion_intent",
        "document_id": doc.document_id, "tenant_id": doc.tenant_id,
        "owner_id": doc.owner_id, "doc_version": doc.doc_version,
        "acl_version": doc.acl_version,
        "document_record_index": index,
        "document_line_sha256": hashlib.sha256((document_line + "\n").encode()).hexdigest(),
        "profile": {
            "repo_id": "BAAI/bge-reranker-v2-m3", "revision": "a" * 40,
            "tokenizer_sha256": "b" * 64, "tokenizers_version": "0.22.2",
            "max_passage_tokens": 10, "overlap_tokens": 0,
        },
        "generation": {
            "qdrant_origin": "https://qdrant.example", "collection": "physical-1",
            "generation_uuid": str(uuid.UUID("12345678-1234-4234-8234-123456789abc")),
            "operator_receipt_sha256": "c" * 64,
        },
        "points": [{"id": p["id"], "payload": p["payload"]} for p in points],
    }


def confirmation(event: dict, *, intent_index: int = 2, intent_line: str | None = None) -> dict:
    if intent_line is None:
        intent_line = json.dumps(event, sort_keys=True, separators=(",", ":"))
    return {
        "event_version": 1, "kind": "ingestion_confirmed",
        "document_id": event["document_id"], "tenant_id": event["tenant_id"],
        "owner_id": event["owner_id"], "doc_version": event["doc_version"],
        "acl_version": event["acl_version"],
        "document_record_index": event["document_record_index"],
        "document_line_sha256": event["document_line_sha256"],
        "intent_record_index": intent_index,
        "intent_line_sha256": hashlib.sha256((intent_line + "\n").encode()).hexdigest(),
    }


class IngestionEventReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Path(temporary.name)
        self.registry = CanonicalDocumentRegistry(self.store)
        self.registry.register(document())
        self.document_line = self.registry.path.read_text().splitlines()[0]

    def replay(self, *events, anchor_version=3):
        lines = [self.document_line] + [json.dumps(e, sort_keys=True, separators=(",", ":")) for e in events]
        payload = ("\n".join(lines) + "\n").encode("ascii")
        self.registry.path.write_bytes(payload)
        anchor = json.loads(self.registry.anchor_path.read_text())
        anchor.update(schema_version=anchor_version, records=len(lines), digest=hashlib.sha256(payload).hexdigest())
        self.registry.anchor_path.write_text(json.dumps(anchor))
        return CanonicalDocumentRegistry(self.store)

    def test_intent_and_confirmation_replay_without_changing_acl(self):
        proposed = intent(self.document_line)
        confirmed = confirmation(proposed)
        registry = self.replay(proposed, confirmed)
        self.assertEqual(registry.source("doc-1"), document())
        self.assertEqual(json.loads(registry.anchor_path.read_text())["records"], 3)

    def test_zero_width_token_window_does_not_corrupt_original_chunk_identity(self):
        from rag_hermes.ingestion_events import validate_event
        doc = replace(document(), content="one")
        original_line = json.dumps({**json.loads(self.document_line), "content": "one"},
                                   sort_keys=True, separators=(",", ":"))
        proposed = intent(original_line)
        proposed["profile"]["max_passage_tokens"] = 1
        class SkippingTokenizer:
            def __call__(self, _text, **_kwargs):
                return {"input_ids": [0, 1], "offset_mapping": [(0, 0), (0, 3)]}
        chunks = chunk_document_tokens(
            doc, SkippingTokenizer(), max_passage_tokens=1, overlap_tokens=0,
            tokenizer_name=proposed["profile"]["repo_id"],
            tokenizer_revision=proposed["profile"]["revision"],
        )
        self.assertEqual(len(chunks), 1)
        proposed["points"] = [{"id": point["id"], "payload": point["payload"]}
                              for point in (chunk_to_point(chunk, [1.0]) for chunk in chunks)]
        self.assertEqual(validate_event(
            proposed, document=doc, document_index=1,
            document_digest=hashlib.sha256((original_line + "\n").encode()).hexdigest(),
        ), "ingestion_intent")

    def test_inactive_document_cannot_declare_new_ingestion_intent(self):
        record = json.loads(self.document_line)
        record["state"] = "inactive"
        self.document_line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        proposed = intent(self.document_line)
        with self.assertRaises(CanonicalStoreError):
            self.replay(proposed)

    def test_duplicate_json_key_in_event_is_not_silently_overwritten(self):
        proposed = intent(self.document_line)
        line = json.dumps(proposed, sort_keys=True, separators=(",", ":"))
        duplicate = line.replace('"kind":"ingestion_intent",',
                                 '"kind":"ignored","kind":"ingestion_intent",')
        self.assertNotEqual(line, duplicate)
        payload = (self.document_line + "\n" + duplicate + "\n").encode()
        self.registry.path.write_bytes(payload)
        anchor = json.loads(self.registry.anchor_path.read_text())
        anchor.update(schema_version=3, records=2, digest=hashlib.sha256(payload).hexdigest())
        self.registry.anchor_path.write_text(json.dumps(anchor))
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_legacy_bootstrap_attestation_cannot_bless_event_history(self):
        self.replay(intent(self.document_line))
        payload = self.registry.path.read_bytes()
        self.registry.anchor_path.unlink()
        with self.assertRaises(CanonicalStoreError):
            bootstrap_canonical_anchor(self.store, {
                "records": 2, "digest": hashlib.sha256(payload).hexdigest(),
                "documents": {"doc-1": {
                    "doc_version": 1, "acl_version": 1, "state": "active",
                }},
            })
        self.assertFalse(self.registry.anchor_path.exists())

    def test_v2_anchor_still_reads_document_only_history(self):
        anchor = json.loads(self.registry.anchor_path.read_text())
        anchor["schema_version"] = 2
        self.registry.anchor_path.write_text(json.dumps(anchor))
        registry = CanonicalDocumentRegistry(self.store)
        self.assertEqual(registry.source("doc-1"), document())
        registry.register(replace(document(), allowed_users=("bob",), acl_version=2))
        self.assertEqual(json.loads(registry.anchor_path.read_text())["schema_version"], 3)

    def test_v2_anchor_cannot_attest_event_even_with_matching_digest_and_count(self):
        with self.assertRaises(CanonicalStoreError):
            self.replay(intent(self.document_line), anchor_version=2)

    def test_intent_without_confirmation_does_not_synthesize_one(self):
        proposed = intent(self.document_line)
        self.replay(proposed)
        self.assertEqual(len(self.registry.path.read_text().splitlines()), 2)
        self.assertEqual(json.loads(self.registry.anchor_path.read_text())["records"], 2)

    def test_orphan_confirmation_is_refused(self):
        with self.assertRaises(CanonicalStoreError):
            self.replay(confirmation(intent(self.document_line)))

    def test_duplicate_confirmation_is_refused(self):
        proposed = intent(self.document_line)
        confirmed = confirmation(proposed)
        with self.assertRaises(CanonicalStoreError):
            self.replay(proposed, confirmed, confirmed)

    def test_second_intent_on_same_document_line_is_refused(self):
        proposed = intent(self.document_line)
        with self.assertRaises(CanonicalStoreError):
            self.replay(proposed, proposed)

    def test_confirmation_must_follow_its_intent_without_unrelated_record(self):
        proposed = intent(self.document_line)
        foreign = json.loads(self.document_line)
        foreign["document_id"] = "other-doc"
        with self.assertRaises(CanonicalStoreError):
            self.replay(proposed, foreign, confirmation(proposed))

    def test_confirmation_after_equivalent_reimport_is_not_contemporary(self):
        proposed = intent(self.document_line)
        with self.assertRaises(CanonicalStoreError):
            self.replay(proposed, json.loads(self.document_line), confirmation(proposed))

    def test_intent_on_old_line_after_equivalent_reimport_is_refused(self):
        proposed = intent(self.document_line)
        with self.assertRaises(CanonicalStoreError):
            self.replay(json.loads(self.document_line), proposed)

    def test_confirmation_must_bind_intent_bytes_and_record_index(self):
        proposed = intent(self.document_line)
        for update in ({"intent_line_sha256": "0" * 64}, {"intent_record_index": 1}):
            with self.subTest(update=update), self.assertRaises(CanonicalStoreError):
                self.replay(proposed, {**confirmation(proposed), **update})

    def test_intent_must_bind_document_bytes_index_and_revision(self):
        for update in ({"document_line_sha256": "0" * 64},
                       {"document_record_index": 2}, {"doc_version": 2}):
            with self.subTest(update=update), self.assertRaises(CanonicalStoreError):
                self.replay({**intent(self.document_line), **update})

    def test_exact_event_keys_and_types_are_required(self):
        proposed = intent(self.document_line)
        variants = (
            {**proposed, "event_version": True},
            {**proposed, "event_version": 2},
            {**proposed, "doc_version": True},
            {**proposed, "unexpected": "x"},
            {key: val for key, val in proposed.items() if key != "generation"},
            {**proposed, "profile": {**proposed["profile"], "max_passage_tokens": True}},
            {**proposed, "generation": {**proposed["generation"], "generation_uuid": "not-v4"}},
            {**proposed, "points": [{**proposed["points"][0], "payload": {
                **proposed["points"][0]["payload"], "classification": True,
            }}]},
        )
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(CanonicalStoreError):
                self.replay(variant)

    def test_event_digest_and_line_count_are_in_anchor_prefix(self):
        proposed = intent(self.document_line)
        self.replay(proposed)
        anchor = json.loads(self.registry.anchor_path.read_text())
        self.assertEqual(anchor["records"], 2)
        self.assertEqual(anchor["digest"], hashlib.sha256(self.registry.path.read_bytes()).hexdigest())
        # Preserve schema and count; rewrite a structurally valid event's
        # operator receipt only. The anchored prefix must reject it.
        proposed["generation"]["operator_receipt_sha256"] = "d" * 64
        self.registry.path.write_text(self.document_line + "\n" +
                                      json.dumps(proposed, sort_keys=True, separators=(",", ":")) + "\n")
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_generation_origin_must_not_be_normalized_by_url_parser(self):
        proposed = intent(self.document_line)
        proposed["generation"]["qdrant_origin"] += "\n"
        with self.assertRaises(CanonicalStoreError):
            self.replay(proposed)

    def test_original_qdrant_origin_allows_explicit_loopback_but_not_remote_http(self):
        proposed = intent(self.document_line)
        proposed["generation"]["qdrant_origin"] = "http://127.0.0.1:6333"
        self.assertEqual(self.replay(proposed).source("doc-1"), document())
        proposed["generation"]["qdrant_origin"] = "http://qdrant.example:6333"
        with self.assertRaises(CanonicalStoreError):
            self.replay(proposed)

    def test_v3_anchor_duplicate_schema_key_is_refused(self):
        anchor = self.registry.anchor_path.read_text()
        duplicate = anchor.replace('"schema_version":', '"schema_version":2,"schema_version":')
        self.assertNotEqual(anchor, duplicate)
        self.registry.anchor_path.write_text(duplicate)
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_recovery_verifier_cannot_use_v2_anchor_over_v3_event_prefix(self):
        proposed = intent(self.document_line)
        self.replay(proposed, confirmation(proposed))
        candidate = (self.document_line + "\n").encode("ascii")
        anchor = json.loads(self.registry.anchor_path.read_text())
        anchor.update(schema_version=2, records=4,
                      digest=hashlib.sha256(self.registry.path.read_bytes() + candidate).hexdigest())
        self.registry.anchor_path.write_text(json.dumps(anchor))
        with self.assertRaises(CanonicalStoreError):
            verify_anchor_recovery_candidate(self.store, candidate)
