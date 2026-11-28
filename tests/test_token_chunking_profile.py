from __future__ import annotations

import hashlib
import io
import json
import logging
from dataclasses import FrozenInstanceError, replace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

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

    def test_production_snapshot_captures_verified_bytes_revision_runtime_and_budgets(self):
        with (patch("rag_hermes.token_chunking_profile._APPROVED_REVISION", "a" * 40),
              patch("rag_hermes.token_chunking_profile._APPROVED_TOKENIZER_SHA256",
                    self.manifest["files"][0]["sha256"]),
              patch("rag_hermes.token_chunking_profile.metadata.version", return_value="0.22.2"),
              patch("tokenizers.Tokenizer.from_str", return_value=object())):
            profile = LockedTokenChunker(
                lock_path=self.lock, tokenizer_path=self.tokenizer_file,
                max_passage_tokens=23, overlap_tokens=5,
            )
        snapshot = profile.verified_profile_snapshot
        self.assertEqual(snapshot.repo_id, self.manifest["repo_id"])
        self.assertEqual(snapshot.revision, "a" * 40)
        self.assertEqual(snapshot.tokenizer_sha256, self.manifest["files"][0]["sha256"])
        self.assertEqual(snapshot.tokenizers_version, "0.22.2")
        self.assertEqual((snapshot.max_passage_tokens, snapshot.overlap_tokens), (23, 5))
        with self.assertRaises(FrozenInstanceError):
            snapshot.revision = "b" * 40
        self.assertNotEqual(snapshot, replace(snapshot, tokenizer_sha256="b" * 64))
        self.assertNotEqual(snapshot, replace(snapshot, revision="b" * 40))
        self.assertNotEqual(snapshot, replace(snapshot, max_passage_tokens=24))
        self.assertNotEqual(snapshot, replace(snapshot, overlap_tokens=6))

    def test_injected_tokenizer_never_receives_trusted_snapshot(self):
        from rag_hermes.token_chunking_profile import _TokenizerAdapter

        for tokenizer in (FakeTokenizer(), _TokenizerAdapter(object())):
            with self.subTest(tokenizer=type(tokenizer).__name__):
                profile = LockedTokenChunker(
                    lock_path=self.lock, tokenizer_path=self.tokenizer_file,
                    tokenizer=tokenizer,
                )
                self.assertIsNone(profile.verified_profile_snapshot)

    def test_fresh_snapshots_detect_changed_verified_inputs(self):
        def construct():
            with (patch("rag_hermes.token_chunking_profile._APPROVED_REVISION",
                        self.manifest["revision"]),
                  patch("rag_hermes.token_chunking_profile._APPROVED_TOKENIZER_SHA256",
                        self.manifest["files"][0]["sha256"]),
                  patch("rag_hermes.token_chunking_profile.metadata.version", return_value="0.22.2"),
                  patch("tokenizers.Tokenizer.from_str", return_value=object())):
                return LockedTokenChunker(
                    lock_path=self.lock, tokenizer_path=self.tokenizer_file,
                    max_passage_tokens=22, overlap_tokens=4,
                ).verified_profile_snapshot

        original = construct()
        self.tokenizer_file.write_bytes(b"changed approved tokenizer")
        self.manifest["files"][0]["sha256"] = hashlib.sha256(self.tokenizer_file.read_bytes()).hexdigest()
        self.lock.write_text(json.dumps(self.manifest), encoding="utf-8")
        changed_bytes = construct()
        self.assertNotEqual(original, changed_bytes)
        self.manifest["revision"] = "b" * 40
        self.lock.write_text(json.dumps(self.manifest), encoding="utf-8")
        changed_revision = construct()
        self.assertNotEqual(changed_bytes, changed_revision)
        self.assertNotEqual(changed_revision, replace(changed_revision, max_passage_tokens=23))
        self.assertNotEqual(changed_revision, replace(changed_revision, overlap_tokens=5))

    def test_snapshot_cannot_be_replaced_or_diverge_from_public_chunking_parameters(self):
        with (patch("rag_hermes.token_chunking_profile._APPROVED_REVISION", "a" * 40),
              patch("rag_hermes.token_chunking_profile._APPROVED_TOKENIZER_SHA256",
                    self.manifest["files"][0]["sha256"]),
              patch("rag_hermes.token_chunking_profile.metadata.version", return_value="0.22.2"),
              patch("tokenizers.Tokenizer.from_str", return_value=object())):
            profile = LockedTokenChunker(lock_path=self.lock, tokenizer_path=self.tokenizer_file)
        snapshot = profile.verified_profile_snapshot
        for attr, value in (("verified_profile_snapshot", None), ("name", "other/repo"),
                            ("revision", "b" * 40), ("max_passage_tokens", 100),
                            ("overlap_tokens", 2)):
            with self.subTest(attr=attr), self.assertRaises(AttributeError):
                setattr(profile, attr, value)
        self.tokenizer_file.write_bytes(b"subsequently changed bytes")
        self.assertIs(profile.verified_profile_snapshot, snapshot)

    def test_snapshot_and_failure_do_not_log_or_expose_tokenizer_bytes_or_paths(self):
        secret = "unique-sensitive-tokenizer-marker"
        self.tokenizer_file.write_bytes(secret.encode())
        self.manifest["files"][0]["sha256"] = hashlib.sha256(self.tokenizer_file.read_bytes()).hexdigest()
        self.lock.write_text(json.dumps(self.manifest), encoding="utf-8")
        stream = io.StringIO()
        logger = logging.getLogger()
        handler = logging.StreamHandler(stream)
        old_level = logger.level
        logger.setLevel(logging.DEBUG)
        self.addCleanup(logger.setLevel, old_level)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        with (redirect_stdout(stream), redirect_stderr(stream),
              patch("rag_hermes.token_chunking_profile._APPROVED_REVISION", "a" * 40),
              patch("rag_hermes.token_chunking_profile._APPROVED_TOKENIZER_SHA256",
                    self.manifest["files"][0]["sha256"]),
              patch("rag_hermes.token_chunking_profile.metadata.version", return_value="0.22.2"),
              patch("tokenizers.Tokenizer.from_str", return_value=object())):
            profile = LockedTokenChunker(lock_path=self.lock, tokenizer_path=self.tokenizer_file)
            self.tokenizer_file.write_bytes(b"changed later")
            with self.assertRaisesRegex(ValueError, "sha256 mismatch") as error:
                LockedTokenChunker(lock_path=self.lock, tokenizer_path=self.tokenizer_file)
        exposed = stream.getvalue() + repr(profile.verified_profile_snapshot) + str(error.exception)
        self.assertNotIn(secret, exposed)
        self.assertNotIn(str(self.tokenizer_file), exposed)
        self.assertNotIn(str(self.lock), exposed)
        self.assertEqual(stream.getvalue(), "")

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
