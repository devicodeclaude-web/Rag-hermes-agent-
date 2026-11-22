"""Reprise SEC-02 : prouver un candidat exact sans modifier le registre."""
from __future__ import annotations

import errno
import json
import multiprocessing
import os
from pathlib import Path
from queue import Empty
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rag_hermes.canonical_registry import (
    CanonicalDocumentRegistry, CanonicalStoreError,
    _record_from_document, verify_anchor_recovery_candidate,
)
from rag_hermes.ingestion import Document


def _verify_in_child(store: Path, candidate: bytes, started, outcome) -> None:
    """Marquer le point juste AVANT l'acquisition du bail partagé."""
    from rag_hermes import canonical_registry as module

    real_open = module._open_tracked_private_file

    def signal_open(*args, **kwargs):
        opened = real_open(*args, **kwargs)
        if kwargs.get("name") == "canonical_transaction.lock":
            started.set()
        return opened

    try:
        with patch.object(module, "_open_tracked_private_file", signal_open):
            module.verify_anchor_recovery_candidate(store, candidate)
        outcome.put("verified")
    except Exception as exc:
        outcome.put(type(exc).__name__)


def _document(version: int, users: tuple[str, ...]) -> Document:
    return Document(
        document_id="doc-1", content="Texte privé", tenant_id="alpha",
        visibility="private", owner_id="alice", allowed_groups=(),
        allowed_users=users, classification=1, doc_version=1,
        source_uri="file:///docs/doc-1.md", acl_version=version,
    )


def _line(doc: Document) -> bytes:
    return (json.dumps(
        _record_from_document(doc), sort_keys=True, separators=(",", ":"),
        allow_nan=False, ensure_ascii=True,
    ) + "\n").encode("ascii")


class RecoveryCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name)
        self.registry = CanonicalDocumentRegistry(self.store)
        self.registry.register(_document(1, ("bob",)))
        self.revocation = _document(2, ())

    def _leave_anchor_ahead(self) -> None:
        real = os.fdopen

        def fail_append(fd, mode="r", *args, **kwargs):
            if "a" in mode:
                raise OSError(errno.ENOSPC, "no space")
            return real(fd, mode, *args, **kwargs)

        with patch("rag_hermes.canonical_registry.os.fdopen", fail_append):
            with self.assertRaises(CanonicalStoreError):
                self.registry.register(self.revocation)

    def test_exact_pending_record_is_verified_without_any_write(self) -> None:
        self._leave_anchor_ahead()
        before = {p.name: p.read_bytes() for p in self.store.iterdir() if p.is_file()}
        verify_anchor_recovery_candidate(self.store, _line(self.revocation))
        after = {p.name: p.read_bytes() for p in self.store.iterdir() if p.is_file()}
        self.assertEqual(after, before)
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_candidate_with_old_acl_is_refused(self) -> None:
        self._leave_anchor_ahead()
        with self.assertRaises(CanonicalStoreError):
            verify_anchor_recovery_candidate(self.store, _line(_document(2, ("bob",))))

    def test_extra_history_is_not_relabelled_as_a_pending_append(self) -> None:
        self._leave_anchor_ahead()
        with self.registry.path.open("ab") as handle:
            handle.write(_line(_document(3, ("bob",))))
        with self.assertRaises(CanonicalStoreError):
            verify_anchor_recovery_candidate(self.store, _line(self.revocation))

    def test_partial_trailing_line_is_not_automatically_discarded(self) -> None:
        self._leave_anchor_ahead()
        with self.registry.path.open("ab") as handle:
            handle.write(b'{"partial":')
        with self.assertRaises(CanonicalStoreError):
            verify_anchor_recovery_candidate(self.store, _line(self.revocation))

    def test_no_gap_and_malformed_candidate_are_refused(self) -> None:
        with self.assertRaises(CanonicalStoreError):
            verify_anchor_recovery_candidate(self.store, _line(self.revocation))
        self._leave_anchor_ahead()
        for bad in (b"not json\n", _line(self.revocation) + b"\n", b"", b"{}\n"):
            with self.subTest(bad=bad), self.assertRaises(CanonicalStoreError):
                verify_anchor_recovery_candidate(self.store, bad)

    def test_exposed_or_symbolic_store_fails_closed(self) -> None:
        self._leave_anchor_ahead()
        self.registry.anchor_path.chmod(0o644)
        with self.assertRaises(CanonicalStoreError):
            verify_anchor_recovery_candidate(self.store, _line(self.revocation))
        self.registry.anchor_path.chmod(0o600)
        decoy = self.store / "elsewhere"
        self.registry.path.rename(decoy)
        self.registry.path.symlink_to(decoy)
        with self.assertRaises(CanonicalStoreError):
            verify_anchor_recovery_candidate(self.store, _line(self.revocation))

    def test_missing_transaction_lock_fails_without_creating_a_new_one(self) -> None:
        self._leave_anchor_ahead()
        lock = self.store / "canonical_transaction.lock"
        lock.unlink()
        with self.assertRaises(CanonicalStoreError):
            verify_anchor_recovery_candidate(self.store, _line(self.revocation))
        self.assertFalse(lock.exists())

    def test_verifier_waits_for_a_cooperating_writer(self) -> None:
        self._leave_anchor_ahead()
        ctx = multiprocessing.get_context("spawn")
        started, outcome = ctx.Event(), ctx.Queue()
        child = ctx.Process(
            target=_verify_in_child,
            args=(self.store, _line(self.revocation), started, outcome),
        )
        try:
            with self.registry.write_guard():
                child.start()
                self.assertTrue(started.wait(30), "child did not open the lock")
                with self.assertRaises(Empty, msg="verifier bypassed the writer's lease"):
                    outcome.get(timeout=0.4)
            child.join(20)
            self.assertFalse(child.is_alive(), "verifier never finished")
            self.assertEqual(child.exitcode, 0)
            self.assertEqual(outcome.get(timeout=5), "verified")
        finally:
            if child.is_alive():
                child.terminate()
                child.join(5)

    def test_cli_reports_only_verdict_and_does_not_edit_store(self) -> None:
        self._leave_anchor_ahead()
        candidate = self.store / "candidate.jsonl"
        candidate.write_bytes(_line(self.revocation))
        candidate.chmod(0o600)
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts/check_canonical_recovery.py"
        env = {**os.environ, "PYTHONPATH": str(root)}
        before = self.registry.path.read_bytes()
        result = subprocess.run(
            [sys.executable, str(script), "--store", str(self.store),
             "--candidate", str(candidate)],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("vérifié", result.stdout)
        self.assertNotIn("Texte privé", result.stdout + result.stderr)
        self.assertEqual(before, self.registry.path.read_bytes())
        candidate.chmod(0o644)
        refused = subprocess.run(
            [sys.executable, str(script), "--store", str(self.store),
             "--candidate", str(candidate)],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertNotIn("Texte privé", refused.stdout + refused.stderr)


if __name__ == "__main__":
    unittest.main()
