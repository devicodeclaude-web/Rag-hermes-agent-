from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import stat
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import patch


def _hold_lock(directory: str, entered, release) -> None:
    from rag_hermes.qdrant_write_lock import document_write_lock
    with document_write_lock(directory, "chunks", "tenant", "doc"):
        entered.set()
        release.wait(10)


class DocumentWriteLockTests(unittest.TestCase):
    def test_different_identity_keys_do_not_alias(self) -> None:
        from rag_hermes.qdrant_write_lock import document_write_lock
        with tempfile.TemporaryDirectory() as directory:
            with document_write_lock(directory, "chunks", "ab", "c", timeout=0.2):
                with document_write_lock(directory, "chunks", "a", "bc", timeout=0.2):
                    pass
            names = [item.name for item in Path(directory).iterdir()]
            self.assertEqual(len(names), 2)
            self.assertEqual(len(set(names)), 2)

    def test_other_process_cannot_enter_same_document_until_release(self) -> None:
        from rag_hermes.qdrant_write_lock import DocumentWriteLockTimeout, document_write_lock
        ctx = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as directory:
            entered, release = ctx.Event(), ctx.Event()
            worker = ctx.Process(target=_hold_lock, args=(directory, entered, release))
            worker.start()
            try:
                self.assertTrue(entered.wait(10), "worker did not acquire lock")
                with self.assertRaisesRegex(DocumentWriteLockTimeout, "lock"):
                    with document_write_lock(directory, "chunks", "tenant", "doc", timeout=0.15):
                        self.fail("second process entered while lock held")
                release.set()
                worker.join(10)
                self.assertEqual(worker.exitcode, 0)
                with document_write_lock(directory, "chunks", "tenant", "doc", timeout=0.5):
                    pass
            finally:
                release.set()
                worker.join(5)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)

    def test_untrusted_lock_path_is_rejected(self) -> None:
        from rag_hermes.qdrant_write_lock import document_write_lock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            shortcut = root / "shortcut"
            shortcut.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(OSError, "lock directory"):
                with document_write_lock(shortcut, "chunks", "tenant", "doc"):
                    pass

    def test_writable_nonsticky_parent_is_rejected_before_creating_lock(self) -> None:
        from rag_hermes.qdrant_write_lock import document_write_lock
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "untrusted"
            parent.mkdir(mode=0o700)
            os.chmod(parent, 0o777)
            target = parent / "private"
            with self.assertRaisesRegex(OSError, "lock directory"):
                with document_write_lock(target, "chunks", "tenant", "doc"):
                    self.fail("unsafe ancestor permitted a lock")
            self.assertFalse(target.exists())

    def test_symlinked_parent_is_rejected(self) -> None:
        from rag_hermes.qdrant_write_lock import document_write_lock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real").mkdir()
            (root / "shortcut").symlink_to(root / "real", target_is_directory=True)
            with self.assertRaisesRegex(OSError, "lock directory"):
                with document_write_lock(root / "shortcut" / "locks", "chunks", "tenant", "doc"):
                    self.fail("symlinked ancestor permitted a lock")

    def test_execute_only_parent_allows_lock(self) -> None:
        from rag_hermes.qdrant_write_lock import document_write_lock
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "execute-only"
            parent.mkdir(mode=0o700)
            target = parent / "private"
            target.mkdir(mode=0o700)
            os.chmod(parent, 0o111)
            try:
                native_open = os.open

                def guard_open(path, flags, *args, **kwargs):
                    # Root bypasses DAC on this host; model the non-root rule.
                    if (path == "execute-only" and flags & os.O_DIRECTORY
                            and not flags & os.O_PATH):
                        raise PermissionError("execute-only parent cannot be read")
                    return native_open(path, flags, *args, **kwargs)

                context = patch("os.open", side_effect=guard_open) if os.geteuid() == 0 else nullcontext()
                with context:
                    with document_write_lock(target, "chunks", "tenant", "doc"):
                        pass
            finally:
                os.chmod(parent, 0o700)

    def test_private_permissions_and_release_after_exception(self) -> None:
        from rag_hermes.qdrant_write_lock import document_write_lock
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "failed during write"):
                with document_write_lock(directory, "chunks", "tenant", "doc"):
                    raise RuntimeError("failed during write")
            lock_files = list(Path(directory).iterdir())
            self.assertEqual(len(lock_files), 1)
            self.assertEqual(stat.S_IMODE(os.stat(lock_files[0]).st_mode), 0o600)
            with document_write_lock(directory, "chunks", "tenant", "doc", timeout=0.2):
                pass

    def test_group_accessible_directory_is_rejected(self) -> None:
        from rag_hermes.qdrant_write_lock import document_write_lock
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o770)
            with self.assertRaisesRegex(OSError, "lock directory"):
                with document_write_lock(directory, "chunks", "tenant", "doc"):
                    pass


if __name__ == "__main__":
    unittest.main()
