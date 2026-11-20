from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import tomllib
import unittest

from rag_hermes.ingestion import Document
from rag_hermes.ingestion import chunk_document
from rag_hermes.acl import AuthorizationContext
from rag_hermes.canonical_registry import CanonicalDocumentRegistry, wrap_repository_with_canonical_barrier
from rag_hermes.retrieval import CanonicalAclError, SearchResult
from rag_hermes.service import RagService
from rag_hermes.token_chunking_profile import LockedTokenChunker


class FakeTokenizer:
    def __call__(self, text, **_kwargs):
        import re
        matches = list(re.finditer(r"\S+", text))
        return {"input_ids": list(range(len(matches))),
                "offset_mapping": [(m.start(), m.end()) for m in matches]}


class LockedTokenChunkerTests(unittest.TestCase):
    def test_server_tokenizer_extra_pins_the_verified_runtime(self):
        project = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertIn(
            "tokenizers==0.22.2", project["project"]["optional-dependencies"]["tokenizer"]
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.tokenizer_file = root / "tokenizer.json"
        self.tokenizer_file.write_bytes(b"test-tokenizer-bytes")
        self.lock = root / "reranker.lock.json"
        self.manifest = {
            "repo_id": "BAAI/bge-reranker-v2-m3",
            "revision": "a" * 40,
            "files": [{"path": "tokenizer.json",
                       "sha256": hashlib.sha256(self.tokenizer_file.read_bytes()).hexdigest()}],
        }
        self.lock.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.document = Document(
            document_id="guide", content="un deux trois quatre cinq six sept",
            tenant_id="alpha", visibility="private", owner_id="alice",
            allowed_groups=(), allowed_users=(), classification=1,
            doc_version=1, source_uri="file:///guide.md",
        )

    def test_pinned_profile_emits_token_metadata_and_offsets(self):
        profile = LockedTokenChunker(
            lock_path=self.lock, tokenizer_path=self.tokenizer_file,
            tokenizer=FakeTokenizer(), max_passage_tokens=3, overlap_tokens=1,
        )
        chunks = profile(self.document)
        self.assertEqual([chunk.text for chunk in chunks],
                         ["un deux trois", "trois quatre cinq", "cinq six sept"])
        self.assertEqual([chunk.token_count for chunk in chunks], [3, 3, 3])
        self.assertEqual({chunk.tokenizer_name for chunk in chunks},
                         {"BAAI/bge-reranker-v2-m3"})
        self.assertEqual({chunk.tokenizer_revision for chunk in chunks}, {"a" * 40})

    def test_wrong_tokenizer_bytes_fail_before_tokenization(self):
        self.tokenizer_file.write_bytes(b"substituted")
        with self.assertRaisesRegex(ValueError, "tokenizer.*sha256"):
            LockedTokenChunker(lock_path=self.lock, tokenizer_path=self.tokenizer_file,
                               tokenizer=FakeTokenizer())

    def test_missing_pin_fails_closed(self):
        self.manifest["files"][0]["sha256"] = None
        self.lock.write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "tokenizer.*sha256"):
            LockedTokenChunker(lock_path=self.lock, tokenizer_path=self.tokenizer_file,
                               tokenizer=FakeTokenizer())

    def test_production_loader_refuses_wrong_tokenizers_version(self):
        from unittest.mock import patch

        with (patch("rag_hermes.token_chunking_profile._APPROVED_REVISION", "a" * 40),
              patch("rag_hermes.token_chunking_profile._APPROVED_TOKENIZER_SHA256",
                    self.manifest["files"][0]["sha256"]),
              patch("importlib.metadata.version", return_value="0.23.2")):
            with self.assertRaisesRegex(ValueError, "tokenizers.*0.22.2"):
                LockedTokenChunker(lock_path=self.lock,
                                   tokenizer_path=self.tokenizer_file)

    def test_production_refuses_a_lock_claiming_an_unapproved_checkpoint(self):
        self.manifest["repo_id"] = "different/claim"
        self.lock.write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "approved.*checkpoint"):
            LockedTokenChunker(lock_path=self.lock, tokenizer_path=self.tokenizer_file)

    def test_legacy_word_chunk_is_refused_before_a_citation(self):
        profile = LockedTokenChunker(
            lock_path=self.lock, tokenizer_path=self.tokenizer_file,
            tokenizer=FakeTokenizer(), max_passage_tokens=3, overlap_tokens=1,
        )
        registry = CanonicalDocumentRegistry(self.temp.name)
        registry.register(self.document)
        old_chunk = chunk_document(self.document)[0]

        class Ranked:
            def search(self, *_args, **_kwargs):
                return [SearchResult(old_chunk, .95)]
            def replace_document(self, *_args):
                raise AssertionError("not called")

        generator_calls = []
        service = RagService(
            repository=wrap_repository_with_canonical_barrier(
                Ranked(), registry, minimum_score=.2, chunker=profile,
            ),
            generator=lambda question, evidence: generator_calls.append(evidence) or "[S1]",
            chunker=profile,
        )
        with self.assertRaisesRegex(CanonicalAclError, "tokenizer profile"):
            service.answer("deux", context=AuthorizationContext("alpha", "alice", (), 1))
        self.assertEqual(generator_calls, [])

    def test_pinned_chunk_is_accepted_by_the_same_canonical_bridge(self):
        profile = LockedTokenChunker(
            lock_path=self.lock, tokenizer_path=self.tokenizer_file,
            tokenizer=FakeTokenizer(), max_passage_tokens=3, overlap_tokens=1,
        )
        registry = CanonicalDocumentRegistry(self.temp.name)
        registry.register(self.document)
        pinned = profile(self.document)[0]

        class Ranked:
            def search(self, *_args, **_kwargs):
                return [SearchResult(pinned, .95)]
            def replace_document(self, *_args):
                raise AssertionError("not called")

        service = RagService(
            repository=wrap_repository_with_canonical_barrier(
                Ranked(), registry, minimum_score=.2, chunker=profile,
            ),
            chunker=profile,
        )
        response = service.answer("deux", context=AuthorizationContext("alpha", "alice", (), 1))
        self.assertFalse(response.abstained)
        self.assertEqual(response.citations[0].quote, pinned.text)
