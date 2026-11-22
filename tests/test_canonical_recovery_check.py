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
    prepare_anchor_recovery_copy,
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

    def test_verified_candidate_creates_a_usable_copy_without_repairing_source(self) -> None:
        self._leave_anchor_ahead()
        original_history = self.registry.path.read_bytes()
        original_anchor = self.registry.anchor_path.read_bytes()
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "recovered"
            prepare_anchor_recovery_copy(self.store, _line(self.revocation), target)
            self.assertEqual(CanonicalDocumentRegistry(target).source("doc-1"), self.revocation)
            self.assertEqual((target / "canonical_anchor.json").read_bytes(), original_anchor)
            self.assertEqual((target / "canonical_documents.jsonl").read_bytes(),
                             original_history + _line(self.revocation))
            self.assertEqual((target / "canonical_transaction.lock").read_bytes(), b"")
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.registry.path.read_bytes(), original_history)
        self.assertEqual(self.registry.anchor_path.read_bytes(), original_anchor)
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_copy_rejects_wrong_candidate_before_creating_destination(self) -> None:
        self._leave_anchor_ahead()
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "recovered"
            with self.assertRaises(CanonicalStoreError):
                prepare_anchor_recovery_copy(
                    self.store, _line(_document(2, ("bob",))), target
                )
            self.assertFalse(target.exists())

    def test_copy_does_not_overwrite_an_existing_target(self) -> None:
        self._leave_anchor_ahead()
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "recovered"
            target.mkdir()
            with self.assertRaises(CanonicalStoreError):
                prepare_anchor_recovery_copy(self.store, _line(self.revocation), target)
            self.assertTrue(target.is_dir())
            self.assertEqual(list(target.iterdir()), [])

    def test_copy_rejects_exposed_parent_and_inside_source(self) -> None:
        self._leave_anchor_ahead()
        with tempfile.TemporaryDirectory() as parent:
            Path(parent).chmod(0o755)
            with self.assertRaises(CanonicalStoreError):
                prepare_anchor_recovery_copy(
                    self.store, _line(self.revocation), Path(parent) / "recovered"
                )
        with self.assertRaises(CanonicalStoreError):
            prepare_anchor_recovery_copy(
                self.store, _line(self.revocation), self.store / "recovered"
            )
        self.assertFalse((self.store / "recovered").exists())

    def test_failed_copy_does_not_publish_a_partial_target(self) -> None:
        self._leave_anchor_ahead()
        from rag_hermes import canonical_registry as module
        real_write = module._write_recovery_file
        count = 0

        def fail_second_file(*args):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError(errno.ENOSPC, "no space")
            return real_write(*args)

        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "recovered"
            with patch.object(module, "_write_recovery_file", fail_second_file):
                with self.assertRaises(CanonicalStoreError):
                    prepare_anchor_recovery_copy(self.store, _line(self.revocation), target)
            self.assertEqual(list(Path(parent).iterdir()), [], "partial staging leaked")

    def test_copy_refuses_target_created_at_publication_time(self) -> None:
        self._leave_anchor_ahead()
        from rag_hermes import canonical_registry as module
        real_rename = module._rename_recovery_noreplace

        def competing_target(parent_fd, source, target):
            os.mkdir(target, dir_fd=parent_fd)
            return real_rename(parent_fd, source, target)

        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "recovered"
            with patch.object(module, "_rename_recovery_noreplace", competing_target):
                with self.assertRaises(CanonicalStoreError):
                    prepare_anchor_recovery_copy(self.store, _line(self.revocation), target)
            self.assertEqual(list(Path(parent).iterdir()), [target])
            self.assertEqual(list(target.iterdir()), [], "concurrent target was replaced")

    def test_failure_after_rename_reports_failure_but_copy_remains_checkable(self) -> None:
        self._leave_anchor_ahead()
        from rag_hermes import canonical_registry as module
        real_fsync = module.os.fsync
        calls = 0

        def fail_parent_fsync(fd):
            nonlocal calls
            calls += 1
            if calls == 5:  # 3 fichiers, répertoire de staging, parent après rename.
                raise OSError(errno.EIO, "durability unknown")
            return real_fsync(fd)

        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "recovered"
            before = self.registry.path.read_bytes()
            with patch("rag_hermes.canonical_registry.os.fsync", fail_parent_fsync):
                with self.assertRaises(CanonicalStoreError):
                    prepare_anchor_recovery_copy(self.store, _line(self.revocation), target)
            self.assertEqual(calls, 5)
            self.assertEqual(self.registry.path.read_bytes(), before)
            self.assertEqual(CanonicalDocumentRegistry(target).source("doc-1"), self.revocation)

    def test_copy_refuses_parent_path_swap_during_staging(self) -> None:
        """Vérifier le staging par PATH peut valider un autre répertoire."""
        self._leave_anchor_ahead()
        with tempfile.TemporaryDirectory() as base:
            parent = Path(base) / "parent"
            parent.mkdir(mode=0o700)
            moved = Path(base) / "moved"
            target = parent / "recovered"
            real_mkdir = os.mkdir

            def swap_after_stage(name, mode=0o777, *, dir_fd=None):
                result = real_mkdir(name, mode, dir_fd=dir_fd)
                if isinstance(name, str) and ".recovery-" in name:
                    parent.rename(moved)
                    real_mkdir(parent, 0o700)
                    decoy = parent / name
                    real_mkdir(decoy, 0o700)
                    (decoy / "canonical_documents.jsonl").write_bytes(
                        self.registry.path.read_bytes() + _line(self.revocation)
                    )
                    (decoy / "canonical_anchor.json").write_bytes(
                        self.registry.anchor_path.read_bytes()
                    )
                    (decoy / "canonical_transaction.lock").write_bytes(b"")
                    for child in decoy.iterdir():
                        child.chmod(0o600)
                return result

            with patch("rag_hermes.canonical_registry.os.mkdir", swap_after_stage):
                with self.assertRaises(CanonicalStoreError):
                    prepare_anchor_recovery_copy(self.store, _line(self.revocation), target)
            self.assertFalse(target.exists())

    def test_copy_refuses_output_parent_replaced_by_source_after_precheck(self) -> None:
        self._leave_anchor_ahead()
        with tempfile.TemporaryDirectory() as base:
            parent = Path(base) / "out"
            parent.mkdir(mode=0o700)
            moved_parent = Path(base) / "old-out"
            target = parent / "recovered"
            from rag_hermes import canonical_registry as module
            real_open = module._open_private_dir
            switched = False

            def swap_parent(path):
                nonlocal switched
                if Path(path) == parent and not switched:
                    switched = True
                    parent.rename(moved_parent)
                    self.store.rename(parent)
                return real_open(path)

            try:
                with patch.object(module, "_open_private_dir", swap_parent):
                    with self.assertRaises(CanonicalStoreError):
                        prepare_anchor_recovery_copy(self.store, _line(self.revocation), target)
                self.assertEqual(list(parent.glob("*.recovery-*")), [])
                self.assertFalse(target.exists())
            finally:
                if switched:
                    parent.rename(self.store)
                    moved_parent.rename(parent)

    def test_failure_opening_new_stage_removes_empty_private_directory(self) -> None:
        self._leave_anchor_ahead()
        real_open = os.open

        def fail_stage_open(path, flags, *args, **kwargs):
            if isinstance(path, str) and ".recovery-" in path and flags & os.O_DIRECTORY:
                raise OSError(errno.EIO, "open staging failed")
            return real_open(path, flags, *args, **kwargs)

        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "recovered"
            with patch("rag_hermes.canonical_registry.os.open", fail_stage_open):
                with self.assertRaises(CanonicalStoreError):
                    prepare_anchor_recovery_copy(self.store, _line(self.revocation), target)
            self.assertEqual(list(Path(parent).iterdir()), [], "empty staging remained")

    def test_anchor_copy_uses_the_descriptor_that_was_validated(self) -> None:
        self._leave_anchor_ahead()
        from rag_hermes import canonical_registry as module
        real_open = module._open_private_file
        anchor_opens = 0

        def count_anchor_open(*args, **kwargs):
            nonlocal anchor_opens
            if kwargs.get("name") == "canonical_anchor.json":
                anchor_opens += 1
            return real_open(*args, **kwargs)

        with patch.object(module, "_open_private_file", count_anchor_open):
            verify_anchor_recovery_candidate(self.store, _line(self.revocation))
        self.assertEqual(anchor_opens, 1)

    def test_stage_directory_fsync_failure_leaves_no_published_copy(self) -> None:
        self._leave_anchor_ahead()
        real_fsync = os.fsync
        calls = 0

        def fail_stage_dir_fsync(fd):
            nonlocal calls
            calls += 1
            if calls == 4:  # Trois fichiers terminés ; fsync du répertoire.
                raise OSError(errno.EIO, "stage directory fsync failed")
            return real_fsync(fd)

        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "recovered"
            with patch("rag_hermes.canonical_registry.os.fsync", fail_stage_dir_fsync):
                with self.assertRaises(CanonicalStoreError):
                    prepare_anchor_recovery_copy(self.store, _line(self.revocation), target)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(parent).iterdir()), [])

    def test_unavailable_noreplace_rename_leaves_no_published_copy(self) -> None:
        self._leave_anchor_ahead()
        from rag_hermes import canonical_registry as module
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "recovered"
            with patch.object(module.ctypes, "CDLL", return_value=object()):
                with self.assertRaises(CanonicalStoreError):
                    prepare_anchor_recovery_copy(self.store, _line(self.revocation), target)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(parent).iterdir()), [])

    def test_cleanup_error_does_not_leak_staging_descriptor(self) -> None:
        self._leave_anchor_ahead()
        from rag_hermes import canonical_registry as module
        real_write = module._write_recovery_file
        real_unlink = os.unlink
        stage_fd = None

        def fail_second_write(fd, name, payload):
            nonlocal stage_fd
            stage_fd = fd
            if name == "canonical_anchor.json":
                raise OSError(errno.ENOSPC, "no space")
            return real_write(fd, name, payload)

        def fail_cleanup(name, *args, **kwargs):
            if name == "canonical_documents.jsonl" and kwargs.get("dir_fd") == stage_fd:
                raise OSError(errno.EIO, "cleanup failed")
            return real_unlink(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as parent:
            with patch.object(module, "_write_recovery_file", fail_second_write), \
                 patch("rag_hermes.canonical_registry.os.unlink", fail_cleanup):
                with self.assertRaises(CanonicalStoreError):
                    prepare_anchor_recovery_copy(
                        self.store, _line(self.revocation), Path(parent) / "recovered"
                    )
            self.assertIsNotNone(stage_fd)
            assert stage_fd is not None
            try:
                with self.assertRaises(OSError, msg="staging directory descriptor leaked"):
                    os.fstat(stage_fd)
            finally:
                try:
                    os.close(stage_fd)
                except OSError:
                    pass

    def test_copy_refuses_output_inside_the_source_actually_opened_after_parent_swap(self) -> None:
        """L'ancien chemin source peut diverger de l'inode ouvert après prévol."""
        self._leave_anchor_ahead()
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            alias = root / "alias"
            alias.mkdir(mode=0o700)
            old_alias = root / "old-alias"
            old_store = alias / "store"
            old_store.mkdir(mode=0o700)
            private = root / "private"
            private.mkdir(mode=0o700)
            actual = private / "store"
            actual.mkdir(mode=0o700)
            for store in (old_store, actual):
                for name in ("canonical_documents.jsonl", "canonical_anchor.json",
                             "canonical_transaction.lock"):
                    (store / name).write_bytes((self.store / name).read_bytes())
                    (store / name).chmod(0o600)
            output_parent = actual / "output"
            output_parent.mkdir(mode=0o700)
            target = output_parent / "prepared"
            original_resolve = Path.resolve
            switched = False

            def swap_after_source_preflight(path, *args, **kwargs):
                nonlocal switched
                result = original_resolve(path, *args, **kwargs)
                if path == old_store and not switched:
                    alias.rename(old_alias)
                    alias.symlink_to(private, target_is_directory=True)
                    switched = True
                return result

            try:
                with patch.object(Path, "resolve", swap_after_source_preflight):
                    with self.assertRaises(CanonicalStoreError):
                        prepare_anchor_recovery_copy(old_store, _line(self.revocation), target)
                self.assertFalse(target.exists())
                self.assertEqual(list(output_parent.iterdir()), [], "wrote inside actual source")
            finally:
                if switched:
                    alias.unlink()
                    old_alias.rename(alias)

    def test_ancestry_closes_new_parent_descriptor_on_stat_failure(self) -> None:
        from rag_hermes import canonical_registry as module
        real_open, real_fstat = os.open, os.fstat
        above_fd = None

        def track_open(path, *args, **kwargs):
            nonlocal above_fd
            fd = real_open(path, *args, **kwargs)
            if path == "..":
                above_fd = fd
            return fd

        def fail_parent_stat(fd):
            if fd == above_fd:
                raise OSError(errno.EIO, "parent stat unavailable")
            return real_fstat(fd)

        own = real_open(self.store, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with patch("rag_hermes.canonical_registry.os.open", track_open), \
                 patch("rag_hermes.canonical_registry.os.fstat", fail_parent_stat):
                with self.assertRaises(OSError):
                    module._directory_descends_from(own, (-1, -1))
            assert above_fd is not None
            try:
                with self.assertRaises(OSError, msg="parent descriptor leaked"):
                    real_fstat(above_fd)
            finally:
                try:
                    os.close(above_fd)
                except OSError:
                    pass
        finally:
            os.close(own)

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

    def test_cli_output_dir_prepares_private_copy_not_source(self) -> None:
        self._leave_anchor_ahead()
        with tempfile.TemporaryDirectory() as parent:
            candidate = Path(parent) / "candidate.jsonl"
            candidate.write_bytes(_line(self.revocation))
            candidate.chmod(0o600)
            output = Path(parent) / "prepared"
            root = Path(__file__).resolve().parents[1]
            script = root / "scripts/check_canonical_recovery.py"
            before = self.registry.path.read_bytes()
            result = subprocess.run(
                [sys.executable, str(script), "--store", str(self.store),
                 "--candidate", str(candidate), "--output-dir", str(output)],
                capture_output=True, text=True, check=False,
                env={**os.environ, "PYTHONPATH": str(root)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Copie", result.stdout)
            self.assertNotIn("Texte privé", result.stdout + result.stderr)
            self.assertEqual(self.registry.path.read_bytes(), before)
            self.assertEqual(CanonicalDocumentRegistry(output).source("doc-1"),
                             self.revocation)
            refused = subprocess.run(
                [sys.executable, str(script), "--store", str(self.store),
                 "--candidate", str(candidate), "--output-dir", str(output)],
                capture_output=True, text=True, check=False,
                env={**os.environ, "PYTHONPATH": str(root)},
            )
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("source inchangée", refused.stdout)
            self.assertNotIn("aucune modification effectuée", refused.stdout)

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
