"""Registre documentaire canonique de la V1 (SEC-01) : tests CPU.

Ces tests éprouvent l'autorité ACL canonique *locale* alimentée par les imports
authentifiés, indépendante de l'index Qdrant, et son branchement en barrière de
lecture. Aucun Qdrant, aucun modèle, aucun GPU.
"""

from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import contextlib
import errno
import hashlib
from io import BytesIO
import json
import multiprocessing
import os
from pathlib import Path
import signal
import stat
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from rag_hermes.acl import AuthorizationContext
from rag_hermes.canonical_registry import (
    CanonicalDocumentRegistry,
    CanonicalStoreError,
    CanonicalWriteThrough,
    wrap_repository_with_canonical_barrier,
)
from rag_hermes.canonical_registry import _record_from_document as _record_of
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.http_api import make_app
from rag_hermes.retrieval import CanonicalAclError, CanonicalAclSearch, SearchResult
from rag_hermes.service import RagService



def document(
    document_id: str = "doc-1",
    *,
    content: str = "Installez Hermes avec pipx puis lancez hermes --tui.",
    tenant_id: str = "alpha",
    owner_id: str = "alice",
    visibility: str = "private",
    classification: int = 1,
    doc_version: int = 1,
    acl_version: int = 1,
    allowed_groups: tuple[str, ...] = (),
    allowed_users: tuple[str, ...] = (),
) -> Document:
    return Document(
        document_id=document_id,
        content=content,
        tenant_id=tenant_id,
        visibility=visibility,
        owner_id=owner_id,
        allowed_groups=allowed_groups,
        allowed_users=allowed_users,
        classification=classification,
        doc_version=doc_version,
        source_uri=f"file:///docs/{document_id}.md",
        acl_version=acl_version,
    )


def _revoke_in_another_process(store: Path) -> None:
    CanonicalDocumentRegistry(store).register(
        document(allowed_users=(), acl_version=2)
    )


def _hold_canonical_read_in_child(store: Path, entered, release) -> None:
    registry = CanonicalDocumentRegistry(store)
    with registry.read_guard():
        entered.set()
        if not release.wait(10):
            raise TimeoutError("test child read lease not released")


def _nested_registry_guard_in_child(store: Path, outer_mode: str) -> None:
    first = CanonicalDocumentRegistry(store)
    second = CanonicalDocumentRegistry(store)
    if outer_mode == "write":
        with first.write_guard(), second.read_guard():
            assert second.source("doc-1") is not None
    else:
        with first.read_guard():
            try:
                with second.write_guard():
                    raise AssertionError("read lease was upgraded")
            except CanonicalStoreError:
                pass


def _forked_child_reads_when_ready(store: Path, started, acquired) -> None:
    registry = CanonicalDocumentRegistry(store)
    started.set()
    with registry.read_guard():
        acquired.set()


def _forked_child_reacquires_after_release(store: Path, released) -> None:
    if not released.wait(5):
        raise TimeoutError("parent did not release lock")
    registry = CanonicalDocumentRegistry(store)
    with registry.read_guard():
        assert registry.source("doc-1") is not None


def _idle_forked_child(ready, release) -> None:
    ready.set()
    if not release.wait(10):
        raise TimeoutError("test child was not released")


def _register_pausing_after_the_anchor(store: Path, published, release) -> None:
    """Publier l'ancre, garder le bail d'écriture, puis laisser l'append finir."""
    from unittest.mock import patch as _patch

    registry = CanonicalDocumentRegistry(store)
    real_write = CanonicalDocumentRegistry._write_anchor

    def pause_after_publish(self, dir_fd, anchor):  # noqa: ANN001
        real_write(self, dir_fd, anchor)
        published.set()
        if not release.wait(10):
            raise TimeoutError("test writer was not released")

    with _patch.object(CanonicalDocumentRegistry, "_write_anchor", pause_after_publish):
        registry.register(document())


def _register_in_another_process(store: Path) -> None:
    CanonicalDocumentRegistry(store).register(document())


def _read_in_another_process(store: Path, started, outcome) -> None:
    started.set()
    try:
        CanonicalDocumentRegistry(store).source("doc-1")
        outcome.put("accepted")
    except CanonicalStoreError as exc:
        outcome.put(f"refused: {exc}")


class _StillBlocked(Exception):
    """Sentinelle du chien de garde.

    PAS une sous-classe d'OSError : `TimeoutError` en est une, donc le code
    sous test la convertirait en `CanonicalStoreError` et un blocage réel
    passerait pour un refus propre.
    """


@contextlib.contextmanager
def _bounded(seconds: float = 2.0):
    """Faire ÉCHOUER une ouverture bloquante au lieu de suspendre la suite."""
    def _expire(_signum, _frame):
        raise _StillBlocked("blocking open was not refused")

    previous = signal.signal(signal.SIGALRM, _expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _wait_for_child(test, child_pid: int, *, timeout: float = 5.0) -> None:
    """Join a forked child WITHOUT hanging the suite if it deadlocks."""
    deadline = time.monotonic() + timeout
    while True:
        waited, status = os.waitpid(child_pid, os.WNOHANG)
        if waited == child_pid:
            test.assertEqual(os.waitstatus_to_exitcode(status), 0)
            return
        if time.monotonic() >= deadline:
            os.kill(child_pid, signal.SIGKILL)
            os.waitpid(child_pid, 0)
            test.fail("forked child blocked on inherited state")
        time.sleep(0.02)


class FakeRepository:
    """Double fidèle du dépôt : enregistre les écritures et sert des résultats."""

    def __init__(self, results: list[SearchResult] | None = None) -> None:
        self.written: list[tuple[str, int]] = []
        self.searches: list[tuple[str, int]] = []
        self.results = results or []

    def replace_document(self, document, chunks):  # noqa: ANN001
        materialized = list(chunks)
        self.written.append((document.document_id, len(materialized)))

        class _Result:
            document_id = document.document_id
            chunk_count = len(materialized)

        return _Result()

    def search(self, query, *, context, limit=10):  # noqa: ANN001
        self.searches.append((query, limit))
        return self.results[:limit]


class RegistryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Path(self._tmp.name)

    def test_registered_document_is_readable_and_survives_a_new_instance(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        doc = document()
        registry.register(doc)

        self.assertEqual(registry.source("doc-1"), doc)

        reloaded = CanonicalDocumentRegistry(self.store)
        self.assertEqual(reloaded.source("doc-1"), doc)
        policy = reloaded.authority.policy_for("doc-1")
        assert policy is not None
        self.assertEqual(policy.tenant_id, "alpha")
        self.assertEqual(policy.owner_id, "alice")
        self.assertEqual(policy.classification, 1)
        self.assertEqual(policy.acl_version, 1)

    def test_new_file_remains_private_with_umask_022(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        previous = os.umask(0o022)
        try:
            registry.register(document(content="document confidentiel"))
        finally:
            os.umask(previous)
        path = self.store / "canonical_documents.jsonl"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(path.stat().st_uid, os.geteuid())
        self.assertEqual(stat.S_IMODE(self.store.stat().st_mode), 0o700)
        self.assertEqual(CanonicalDocumentRegistry(self.store).source("doc-1"),
                         document(content="document confidentiel"))

    def test_permissive_directory_is_refused_before_creating_file(self) -> None:
        self.store.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "canonical store directory.*permissions"):
            CanonicalDocumentRegistry(self.store)
        self.assertFalse((self.store / "canonical_documents.jsonl").exists())

    def test_existing_permissive_file_is_refused_without_chmod_or_append(self) -> None:
        path = self.store / "canonical_documents.jsonl"
        path.write_text("unchanged\n", encoding="utf-8")
        path.chmod(0o644)
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)
        self.assertEqual(path.read_text(encoding="utf-8"), "unchanged\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)

    def test_file_permissions_changed_after_startup_refuse_append(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        path = self.store / "canonical_documents.jsonl"
        original = path.read_bytes()
        path.chmod(0o644)
        with self.assertRaises(CanonicalStoreError):
            registry.register(document(doc_version=2))
        self.assertEqual(path.read_bytes(), original)
        # Après exposition du fichier, la lecture ne doit pas servir un cache.
        with self.assertRaises(CanonicalStoreError):
            registry.source("doc-1")

    def test_directory_permissions_changed_after_startup_refuse_append(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        self.store.chmod(0o755)
        with self.assertRaises(CanonicalStoreError):
            registry.register(document())
        self.assertFalse((self.store / "canonical_documents.jsonl").exists())

    def test_symlinked_store_file_is_refused_without_touching_target(self) -> None:
        target = self.store / "target"
        target.write_bytes(b"secret\n")
        target.chmod(0o600)
        (self.store / "canonical_documents.jsonl").symlink_to(target)
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)
        self.assertEqual(target.read_bytes(), b"secret\n")

    def test_store_file_replaced_by_symlink_after_startup_refuses_append(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        target = self.store / "target"
        target.write_bytes(b"unchanged\n")
        target.chmod(0o600)
        (self.store / "canonical_documents.jsonl").symlink_to(target)
        with self.assertRaises(CanonicalStoreError):
            registry.register(document())
        self.assertEqual(target.read_bytes(), b"unchanged\n")
        with self.assertRaises(CanonicalStoreError):
            registry.source("doc-1")

    def test_store_directory_symlink_is_refused(self) -> None:
        link = self.store.parent / (self.store.name + "-link")
        link.symlink_to(self.store, target_is_directory=True)
        self.addCleanup(link.unlink)
        with self.assertRaisesRegex(ValueError, "symlink"):
            CanonicalDocumentRegistry(link)

    def test_store_directory_must_be_an_existing_absolute_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute"):
            CanonicalDocumentRegistry(Path("relative/store"))
        with self.assertRaisesRegex(ValueError, "directory"):
            CanonicalDocumentRegistry(self.store / "doc.jsonl")

    def test_unknown_document_has_no_source_and_no_policy(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        self.assertIsNone(registry.source("absent"))
        self.assertIsNone(registry.authority.policy_for("absent"))
        allowed, reason = registry.authority.authorize(
            "absent", 1, AuthorizationContext("alpha", "alice", (), 1)
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "unknown_document")

    def test_boolean_integers_are_refused_without_writing_anything(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        for field in ("classification", "doc_version", "acl_version"):
            with self.subTest(field=field):
                forged = document(**{field: True})  # type: ignore[arg-type]
                with self.assertRaisesRegex(ValueError, field):
                    registry.register(forged)
        self.assertIsNone(registry.source("doc-1"))
        self.assertEqual(list(self.store.glob("*.jsonl")), [])

    def test_acl_containers_must_be_tuples_of_exact_strings(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        cases = (
            ("allowed_groups", ["ops"]),
            ("allowed_users", ["bob"]),
            ("allowed_groups", (1,)),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, field):
                    registry.register(document(**{field: value}))  # type: ignore[arg-type]
        self.assertIsNone(registry.source("doc-1"))

    def test_str_subclass_with_lying_equality_is_refused(self) -> None:
        class Sosie(str):
            def __eq__(self, other: object) -> bool:  # pragma: no cover - sondé
                return True

            def __ne__(self, other: object) -> bool:  # pragma: no cover - sondé
                return False

            def __hash__(self) -> int:
                return hash(str(self))

        registry = CanonicalDocumentRegistry(self.store)
        with self.assertRaisesRegex(ValueError, "tenant_id"):
            registry.register(document(tenant_id=Sosie("alpha")))

    def test_non_document_objects_and_subclasses_are_refused(self) -> None:
        class Heritier(Document):
            pass

        registry = CanonicalDocumentRegistry(self.store)
        with self.assertRaisesRegex(ValueError, "Document"):
            registry.register(object())  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "Document"):
            registry.register(
                Heritier(
                    document_id="doc-1",
                    content="x",
                    tenant_id="alpha",
                    visibility="private",
                    owner_id="alice",
                    allowed_groups=(),
                    allowed_users=(),
                    classification=1,
                    doc_version=1,
                    source_uri="file:///docs/doc-1.md",
                )
            )

    def test_control_characters_in_identity_fields_are_refused(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        with self.assertRaisesRegex(ValueError, "document_id"):
            registry.register(document("doc\n1"))
        with self.assertRaisesRegex(ValueError, "document_id"):
            registry.register(document(""))

    def test_same_document_id_from_another_tenant_is_refused(self) -> None:
        """L'autorité canonique indexe par document_id SEUL : collision = refus."""
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(tenant_id="alpha", owner_id="alice"))

        with self.assertRaisesRegex(ValueError, "tenant"):
            registry.register(document(tenant_id="beta", owner_id="bob"))

        policy = registry.authority.policy_for("doc-1")
        assert policy is not None
        self.assertEqual(policy.tenant_id, "alpha")

    def test_version_regression_is_refused_in_both_axes(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(doc_version=3, acl_version=4))

        with self.assertRaisesRegex(ValueError, "doc_version"):
            registry.register(document(doc_version=2, acl_version=4))
        with self.assertRaisesRegex(ValueError, "acl_version"):
            registry.register(document(doc_version=3, acl_version=3))

        policy = registry.authority.policy_for("doc-1")
        assert policy is not None
        self.assertEqual(policy.acl_version, 4)

    def test_owner_change_is_refused_even_within_the_same_tenant(self) -> None:
        """La V1 ne transfère pas la propriété ; le registre écrit AVANT l'index.

        Sans ce refus, une reprise que le dépôt rejetterait ensuite laisserait
        l'autorité canonique attribuer le document à l'usurpateur, et le vrai
        propriétaire se verrait refuser ses propres passages (échec fermé).
        """
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(owner_id="alice"))

        # PermissionError : la couche HTTP doit rendre 403, pas 400.
        with self.assertRaisesRegex(PermissionError, "owner_id"):
            registry.register(document(owner_id="bob", doc_version=2))

        stored = registry.source("doc-1")
        assert stored is not None
        self.assertEqual(stored.owner_id, "alice")
        self.assertEqual(stored.doc_version, 1)

    def test_acl_change_at_equal_version_is_refused_without_touching_authority(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",)))
        original = registry.path.read_bytes()

        with self.assertRaisesRegex(ValueError, "acl_version"):
            registry.register(document(allowed_users=()))

        self.assertEqual(registry.path.read_bytes(), original)
        policy = registry.authority.policy_for("doc-1")
        assert policy is not None
        self.assertEqual(policy.allowed_users, ("bob",))
        reloaded = CanonicalDocumentRegistry(self.store)
        self.assertEqual(reloaded.authority.policy_for("doc-1"), policy)

    def test_old_allowlist_replayed_after_revocation_is_refused(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        registry.register(document(allowed_users=(), acl_version=2))
        original = registry.path.read_bytes()

        with self.assertRaisesRegex(ValueError, "acl_version"):
            registry.register(document(allowed_users=("bob",), acl_version=2))

        self.assertEqual(registry.path.read_bytes(), original)
        policy = registry.authority.policy_for("doc-1")
        assert policy is not None
        self.assertEqual(policy.acl_version, 2)
        self.assertEqual(policy.allowed_users, ())
        self.assertEqual(CanonicalDocumentRegistry(self.store).authority.policy_for("doc-1"), policy)

    def test_second_registry_cannot_replay_acl_after_first_revokes(self) -> None:
        first = CanonicalDocumentRegistry(self.store)
        first.register(document(allowed_users=("bob",), acl_version=1))
        second = CanonicalDocumentRegistry(self.store)
        first.register(document(allowed_users=(), acl_version=2))
        before = first.path.read_bytes()

        with self.assertRaisesRegex(ValueError, "acl_version"):
            second.register(document(allowed_users=("bob",), acl_version=2))

        self.assertEqual(first.path.read_bytes(), before)
        stored = CanonicalDocumentRegistry(self.store).source("doc-1")
        assert stored is not None
        self.assertEqual(stored.allowed_users, ())

    def test_second_registry_reads_revoked_policy_without_restart(self) -> None:
        writer = CanonicalDocumentRegistry(self.store)
        writer.register(document(allowed_users=("bob",), acl_version=1))
        reader = CanonicalDocumentRegistry(self.store)
        writer.register(document(allowed_users=(), acl_version=2))

        policy = reader.authority.policy_for("doc-1")
        assert policy is not None
        self.assertEqual(policy.acl_version, 2)
        self.assertEqual(policy.allowed_users, ())
        self.assertEqual(reader.source("doc-1"), writer.source("doc-1"))

    def test_other_process_revocation_blocks_replay_and_refreshes_reader(self) -> None:
        reader = CanonicalDocumentRegistry(self.store)
        reader.register(document(allowed_users=("bob",), acl_version=1))
        process = multiprocessing.get_context("spawn").Process(
            target=_revoke_in_another_process, args=(self.store,)
        )
        process.start()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
        self.assertEqual(process.exitcode, 0)
        with self.assertRaisesRegex(ValueError, "acl_version"):
            reader.register(document(allowed_users=("bob",), acl_version=2))
        current = reader.source("doc-1")
        assert current is not None
        self.assertEqual((current.acl_version, current.allowed_users), (2, ()))

    def test_simultaneous_writers_only_one_acl_revision_wins(self) -> None:
        seed = CanonicalDocumentRegistry(self.store)
        seed.register(document(acl_version=1))
        registries = [CanonicalDocumentRegistry(self.store) for _ in range(6)]
        barrier = threading.Barrier(len(registries))

        def write(index: int) -> bool:
            barrier.wait(timeout=10)
            try:
                registries[index].register(document(
                    allowed_users=(f"reader-{index}",), acl_version=2,
                ))
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=len(registries)) as pool:
            accepted = list(pool.map(write, range(len(registries))))
        self.assertEqual(sum(accepted), 1)
        stored = CanonicalDocumentRegistry(self.store).source("doc-1")
        assert stored is not None
        self.assertEqual(stored.allowed_users, (f"reader-{accepted.index(True)}",))

    def test_cross_process_reader_blocks_canonical_write(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(acl_version=1))
        context = multiprocessing.get_context("spawn")
        entered, release = context.Event(), context.Event()
        process = context.Process(
            target=_hold_canonical_read_in_child,
            args=(self.store, entered, release),
        )
        process.start()
        try:
            # Démarrage d'un interpréteur `spawn` : c'est une latence, pas la
            # propriété testée. Un budget serré rendait ce test instable quand
            # la suite entière tourne en parallèle sur une machine chargée.
            self.assertTrue(entered.wait(30))
            started = threading.Event()
            def write():
                started.set()
                return registry.register(document(acl_version=2))

            with ThreadPoolExecutor(max_workers=1) as pool:
                writing = pool.submit(write)
                self.assertTrue(started.wait(5))
                threading.Event().wait(0.15)
                self.assertFalse(writing.done())
                release.set()
                writing.result(timeout=5)
        finally:
            release.set()
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)
        self.assertEqual(process.exitcode, 0)

    def test_transaction_lock_is_private_and_rejects_permissions_change(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        with registry.read_guard():
            pass
        lock_file = self.store / "canonical_transaction.lock"
        self.assertEqual(stat.S_IMODE(lock_file.stat().st_mode), 0o600)
        lock_file.chmod(0o644)
        with self.assertRaises(CanonicalStoreError):
            with registry.read_guard():
                self.fail("permissive transaction lock accepted")

    def test_writer_cannot_upgrade_its_own_read_lease(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        with registry.read_guard():
            with self.assertRaises(CanonicalStoreError):
                registry.register(document())
        self.assertFalse(registry.path.exists())
        registry.register(document())

    def test_same_thread_registry_instances_do_not_deadlock_or_upgrade(self) -> None:
        CanonicalDocumentRegistry(self.store).register(document())
        ctx = multiprocessing.get_context("spawn")
        for mode in ("write", "read"):
            with self.subTest(mode=mode):
                process = ctx.Process(
                    target=_nested_registry_guard_in_child, args=(self.store, mode)
                )
                process.start()
                process.join(8)
                if process.is_alive():
                    process.terminate()
                    process.join(5)
                self.assertEqual(process.exitcode, 0, "nested lease blocked")

    @unittest.skipUnless("fork" in multiprocessing.get_all_start_methods(), "fork unavailable")
    def test_forked_process_waits_for_parent_transaction_lease(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        ctx = multiprocessing.get_context("fork")
        started, acquired = ctx.Event(), ctx.Event()
        with registry.write_guard():
            process = ctx.Process(
                target=_forked_child_reads_when_ready,
                args=(self.store, started, acquired),
            )
            process.start()
            try:
                self.assertTrue(started.wait(2))
                self.assertFalse(acquired.wait(0.2), "child reused parent's write lease")
            except BaseException:
                process.terminate()
                process.join(2)
                raise
        process.join(2)
        if process.is_alive():
            process.terminate()
            process.join(2)
        self.assertEqual(process.exitcode, 0)
        self.assertTrue(acquired.is_set())

    @unittest.skipUnless("fork" in multiprocessing.get_all_start_methods(), "fork unavailable")
    def test_child_forked_by_holder_can_acquire_after_parent_releases(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        released = multiprocessing.get_context("fork").Event()
        with registry.write_guard():
            process = multiprocessing.get_context("fork").Process(
                target=_forked_child_reacquires_after_release,
                args=(self.store, released),
            )
            process.start()
        released.set()
        process.join(2)
        if process.is_alive():
            process.terminate()
            process.join(2)
        self.assertEqual(process.exitcode, 0)

    @unittest.skipUnless(hasattr(os, "fork"), "fork unavailable")
    def test_unwinding_parent_lease_in_forked_child_does_not_close_reused_fd(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        for write in (False, True):
            with self.subTest(write=write):
                child_pid = None
                try:
                    with (registry.write_guard() if write else registry.read_guard()):
                        child_pid = os.fork()
                except BaseException:
                    if child_pid == 0:
                        os._exit(1)
                    raise
                if child_pid == 0:
                    os._exit(0)
                _wait_for_child(self, child_pid)

    @unittest.skipUnless(hasattr(os, "fork"), "fork unavailable")
    def test_child_lease_survives_unwinding_the_inherited_parent_lease(self) -> None:
        """A fresh child lease may reuse the fd number the child just closed."""
        from rag_hermes import canonical_registry as module

        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        stack = contextlib.ExitStack()
        child_pid = None
        with registry.read_guard():
            child_pid = os.fork()
            if child_pid == 0:
                # Shared lease, so this does not block on the parent's.
                stack.enter_context(CanonicalDocumentRegistry(self.store).read_guard())
        if child_pid == 0:
            # The inherited guard above has now unwound inside this child.
            code = 1
            try:
                tracked = dict(module._ACTIVE_TRANSACTION_FDS)
                if len(tracked) == 1:
                    os.fstat(next(iter(tracked.values())))
                    stack.close()
                    code = 0
            except BaseException:
                code = 1
            os._exit(code)
        stack.close()
        _wait_for_child(self, child_pid)

    @unittest.skipUnless(hasattr(os, "fork"), "fork unavailable")
    def test_child_does_not_inherit_a_locked_instance_mutex(self) -> None:
        """A fork while another thread held the instance mutex must not hang."""
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        entered, release = threading.Event(), threading.Event()

        def hold_instance_lock():
            with registry._lock:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("instance lock not released")

        with ThreadPoolExecutor(max_workers=1) as pool:
            holding = pool.submit(hold_instance_lock)
            try:
                self.assertTrue(entered.wait(5))
                child_pid = os.fork()
                if child_pid == 0:
                    code = 1
                    try:
                        # Same instance object, inherited with the mutex held.
                        if registry.source("doc-1") is not None:
                            code = 0
                    except BaseException:
                        code = 1
                    os._exit(code)
                _wait_for_child(self, child_pid)
            finally:
                release.set()
                holding.result(timeout=5)

    @unittest.skipUnless("fork" in multiprocessing.get_all_start_methods(), "fork unavailable")
    def test_idle_child_cannot_keep_other_thread_read_lease_alive(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        entered, stop_reader = threading.Event(), threading.Event()
        ctx = multiprocessing.get_context("fork")
        ready, release_child = ctx.Event(), ctx.Event()

        def hold_read():
            with registry.read_guard():
                entered.set()
                if not stop_reader.wait(5):
                    raise TimeoutError("reader not released")

        with ThreadPoolExecutor(max_workers=2) as pool:
            reading = pool.submit(hold_read)
            self.assertTrue(entered.wait(5))
            child = ctx.Process(target=_idle_forked_child, args=(ready, release_child))
            child.start()
            try:
                self.assertTrue(ready.wait(5))
                stop_reader.set()
                reading.result(timeout=5)
                writing = pool.submit(registry.register, document(acl_version=2))
                try:
                    writing.result(timeout=1)
                finally:
                    release_child.set()
                    writing.result(timeout=5)
            finally:
                stop_reader.set()
                release_child.set()
                child.join(5)
                if child.is_alive():
                    child.terminate()
                    child.join(5)
            self.assertEqual(child.exitcode, 0)

    @unittest.skipUnless("fork" in multiprocessing.get_all_start_methods(), "fork unavailable")
    def test_idle_child_cannot_keep_registry_file_lock_alive(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        entered, stop_writer = threading.Event(), threading.Event()
        ctx = multiprocessing.get_context("fork")
        ready, release_child = ctx.Event(), ctx.Event()
        original = registry._fresh_verified

        def hold_file_lock(fd, dir_fd):
            entered.set()
            if not stop_writer.wait(5):
                raise TimeoutError("writer not released")
            return original(fd, dir_fd)

        with patch.object(registry, "_fresh_verified", side_effect=hold_file_lock):
            with ThreadPoolExecutor(max_workers=2) as pool:
                writing = pool.submit(registry.register, document(acl_version=2))
                self.assertTrue(entered.wait(5))
                child = ctx.Process(target=_idle_forked_child, args=(ready, release_child))
                child.start()
                try:
                    self.assertTrue(ready.wait(5))
                    stop_writer.set()
                    writing.result(timeout=5)
                    next_write = pool.submit(registry.register, document(acl_version=3))
                    try:
                        next_write.result(timeout=1)
                    finally:
                        release_child.set()
                        next_write.result(timeout=5)
                finally:
                    stop_writer.set()
                    release_child.set()
                    child.join(5)
                    if child.is_alive():
                        child.terminate()
                        child.join(5)
                self.assertEqual(child.exitcode, 0)

    def test_registry_does_not_leave_untracked_duplicate_flock_descriptors(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        # Fork closes tracked file descriptors in the child. An os.dup on a
        # tracked flock descriptor would create an untracked inherited lease.
        with patch("rag_hermes.canonical_registry.os.dup", side_effect=AssertionError("untracked flock dup")):
            registry.register(document())
            registry.source("doc-1")
            registry.register(document(acl_version=2))

    def test_unchanged_history_is_not_reparsed_for_each_policy_lookup(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        with patch.object(registry, "_read_documents", wraps=registry._read_documents) as read:
            for _ in range(3):
                self.assertIsNotNone(registry.authority.policy_for("doc-1"))
                self.assertIsNotNone(registry.source("doc-1"))
            self.assertEqual(read.call_count, 0)

    def test_truncated_history_cannot_restore_a_revoked_acl(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        old = document(allowed_users=("bob",), acl_version=1)
        registry.register(old)
        registry.register(document(allowed_users=(), acl_version=2))
        registry.path.write_bytes(b"")
        with self.assertRaises(RuntimeError):
            registry.source("doc-1")
        with self.assertRaises(RuntimeError):
            registry.register(old)
        self.assertEqual(registry.path.read_bytes(), b"")

    def test_restored_old_history_cannot_restore_a_revoked_acl(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        old = document(allowed_users=("bob",), acl_version=1)
        registry.register(old)
        backup = registry.path.read_bytes()
        registry.register(document(allowed_users=(), acl_version=2))
        registry.path.write_bytes(backup)
        with self.assertRaises(RuntimeError):
            registry.source("doc-1")
        with self.assertRaises(RuntimeError):
            registry.register(old)
        self.assertEqual(registry.path.read_bytes(), backup)

    def test_restart_on_a_restored_backup_refuses_the_revoked_acl(self) -> None:
        """Le trou que le cache en mémoire ne peut pas couvrir : un REDÉMARRAGE.

        Un nouveau processus n'a rien observé ; sans repère persisté hors du
        JSONL, il accepte une sauvegarde antérieure et réautorise Bob.
        """
        registry = CanonicalDocumentRegistry(self.store)
        old = document(allowed_users=("bob",), acl_version=1)
        registry.register(old)
        backup = registry.path.read_bytes()
        registry.register(document(allowed_users=(), acl_version=2))
        registry.path.write_bytes(backup)

        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_restart_on_a_truncated_history_is_refused(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        registry.register(document(allowed_users=(), acl_version=2))
        registry.path.write_bytes(b"")

        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_anchor_is_private_and_refused_once_exposed(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        self.assertEqual(stat.S_IMODE(registry.anchor_path.stat().st_mode), 0o600)
        self.assertEqual(registry.anchor_path.stat().st_uid, os.geteuid())
        registry.anchor_path.chmod(0o644)
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_a_tampered_anchor_fails_closed_without_repair(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        original = registry.anchor_path.read_bytes()
        for payload in (
            b"{",
            b"[]",
            b'{"records":1}',
            b'{"records":true,"documents":{}}',
            b'{"records":1,"documents":{"doc-1":{"doc_version":true,"acl_version":1}}}',
            b'{"records":1,"documents":{"doc-1":{"doc_version":1}}}',
            b'{"records":1,"documents":{"doc-1":{"doc_version":1,"acl_version":1,"x":0}}}',
        ):
            with self.subTest(payload=payload):
                registry.anchor_path.write_bytes(payload)
                with self.assertRaises(CanonicalStoreError):
                    CanonicalDocumentRegistry(self.store)
                self.assertEqual(registry.anchor_path.read_bytes(), payload)
        registry.anchor_path.write_bytes(original)
        self.assertIsNotNone(CanonicalDocumentRegistry(self.store).source("doc-1"))

    def test_anchor_symlink_is_refused_without_touching_its_target(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        decoy = Path(self._tmp.name) / "decoy.json"
        decoy.write_bytes(b"unchanged")
        registry.anchor_path.unlink()
        registry.anchor_path.symlink_to(decoy)
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)
        self.assertEqual(decoy.read_bytes(), b"unchanged")

    def test_a_store_predating_the_anchor_keeps_working_then_gains_one(self) -> None:
        """Compatibilité : une installation sans ancre démarre, puis en gagne une."""
        registry = CanonicalDocumentRegistry(self.store)
        revoked = document(allowed_users=(), acl_version=2)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        registry.register(revoked)
        registry.anchor_path.unlink()

        # Sans ancre, la protection au redémarrage n'existe pas encore.
        reopened = CanonicalDocumentRegistry(self.store)
        self.assertEqual(reopened.source("doc-1"), revoked)
        self.assertFalse(reopened.anchor_path.exists())

        # Le premier enregistrement la publie, et elle protège ensuite.
        reopened.register(document(allowed_users=(), acl_version=3))
        self.assertTrue(reopened.anchor_path.exists())
        backup = reopened.path.read_bytes()
        reopened.register(document(allowed_users=(), acl_version=4))
        reopened.path.write_bytes(backup)
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_anchor_survives_a_refused_registration(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        anchor = registry.anchor_path.read_bytes()
        with self.assertRaises(ValueError):
            registry.register(document(allowed_users=(), acl_version=1))
        self.assertEqual(registry.anchor_path.read_bytes(), anchor)
        self.assertIsNotNone(CanonicalDocumentRegistry(self.store).source("doc-1"))

    def test_restart_with_a_deleted_history_but_a_live_anchor_is_refused(self) -> None:
        """Supprimer le JSONL ne doit pas effacer un document déjà ancré."""
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        registry.register(document(allowed_users=(), acl_version=2))
        registry.path.unlink()

        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)
        self.assertFalse(registry.path.exists())

    def test_a_rewritten_history_with_the_same_final_state_is_refused(self) -> None:
        """L'ancre compte les LIGNES : compacter la trace d'audit est refusé."""
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        final = document(allowed_users=(), acl_version=2)
        registry.register(final)
        lines = registry.path.read_bytes().splitlines(keepends=True)
        self.assertEqual(len(lines), 2)

        # État final identique, mais la révision intermédiaire a disparu.
        registry.path.write_bytes(lines[-1])
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_a_dropped_document_with_enough_lines_is_still_refused(self) -> None:
        """Le compte de lignes ne couvre pas la perte d'un document ancré."""
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document("doc-1", allowed_users=("bob",), acl_version=1))
        registry.register(document("doc-2", allowed_users=(), acl_version=1))
        first, second = registry.path.read_bytes().splitlines(keepends=True)

        # Deux lignes comme l'ancre, mais doc-2 a été remplacé par doc-1.
        registry.path.write_bytes(first + first)
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_an_unpublishable_anchor_blocks_the_append(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        before = registry.path.read_bytes()
        anchor = registry.anchor_path.read_bytes()
        with patch.object(
            CanonicalDocumentRegistry, "_write_anchor",
            side_effect=CanonicalStoreError("canonical anchor cannot be published"),
        ):
            with self.assertRaises(CanonicalStoreError):
                registry.register(document(doc_version=2, content="nouveau"))
        self.assertEqual(registry.path.read_bytes(), before)
        self.assertEqual(registry.anchor_path.read_bytes(), anchor)
        reopened = CanonicalDocumentRegistry(self.store).source("doc-1")
        assert reopened is not None
        self.assertEqual(reopened.doc_version, 1)

    def test_a_blocking_node_in_place_of_the_anchor_fails_closed(self) -> None:
        """Un FIFO ne doit jamais suspendre lecture, démarrage ou publication."""
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        for name, target in {
            "anchor": registry.anchor_path,
            "history": registry.path,
        }.items():
            with self.subTest(node=name):
                target.unlink(missing_ok=True)
                os.mkfifo(target, 0o600)
                try:
                    with _bounded():
                        with self.assertRaises(CanonicalStoreError):
                            CanonicalDocumentRegistry(self.store)
                finally:
                    target.unlink(missing_ok=True)

    def test_a_blocking_node_left_at_the_temporary_anchor_is_replaced(self) -> None:
        """Le temporaire est un résidu : on le remplace, sans jamais bloquer."""
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        temporary = self.store / "canonical_anchor.json.new"
        os.mkfifo(temporary, 0o600)
        with _bounded():
            registry.register(document(doc_version=2, content="nouveau"))
        self.assertFalse(temporary.exists())
        reopened = CanonicalDocumentRegistry(self.store).source("doc-1")
        assert reopened is not None
        self.assertEqual(reopened.doc_version, 2)

    def test_a_failed_anchor_publication_leaves_no_temporary_behind(self) -> None:
        """Un temporaire orphelin décrirait un état jamais publié.

        Il est en 0600 donc inoffensif, mais le laisser rend le répertoire
        trompeur pour un opérateur, et le nettoyage doit couvrir le cas
        ATTENDU — `rename` ou écriture en échec — pas seulement l'interruption.
        """
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        temporary = self.store / "canonical_anchor.json.new"

        with patch(
            "rag_hermes.canonical_registry.os.rename",
            side_effect=OSError(errno.EIO, "input/output error"),
        ):
            with self.assertRaises(CanonicalStoreError):
                registry.register(document(doc_version=2, content="nouveau"))
        self.assertFalse(temporary.exists(), "leftover anchor temporary")

    def test_a_temporary_recreated_after_the_unlink_fails_closed(self) -> None:
        """TOCTOU entre le retrait du résidu et la création : `O_EXCL` tranche.

        Sans `O_EXCL` (et sans `O_NONBLOCK`), un FIFO recréé dans cette fenêtre
        suspendrait la publication alors que le verrou exclusif est tenu.
        """
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        temporary = self.store / "canonical_anchor.json.new"
        os.mkfifo(temporary, 0o600)
        before = registry.path.read_bytes()
        try:
            # Le résidu survit au retrait : exactement la fenêtre de course.
            with patch("rag_hermes.canonical_registry.os.unlink"):
                with _bounded():
                    with self.assertRaises(CanonicalStoreError):
                        registry.register(document(doc_version=2, content="nouveau"))
        finally:
            temporary.unlink(missing_ok=True)
        self.assertEqual(registry.path.read_bytes(), before)

    def test_an_append_failure_after_the_anchor_fails_closed_for_reads_too(self) -> None:
        """Toute panne d'append (pas seulement un crash) laisse l'ancre en avance.

        Le processus vivant ne doit PAS continuer à servir son cache : l'ACL
        qu'il garde est précisément celle que l'écriture voulait remplacer.
        """
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        real_fdopen = os.fdopen

        def failing_fdopen(fd, mode="r", *args, **kwargs):
            if "a" in mode:
                raise OSError(errno.ENOSPC, "no space left on device")
            return real_fdopen(fd, mode, *args, **kwargs)

        with patch("rag_hermes.canonical_registry.os.fdopen", failing_fdopen):
            with self.assertRaises(CanonicalStoreError):
                registry.register(document(allowed_users=(), acl_version=2))

        with self.assertRaises(CanonicalStoreError):
            registry.source("doc-1")
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_a_durability_failure_whose_bytes_landed_does_not_brick_the_store(self) -> None:
        """`fsync` qui échoue alors que la ligne EST écrite : pas de brique.

        L'ancre n'est pas en avance, donc refuser pour toujours serait une
        panne de disponibilité fabriquée. L'écriture est signalée (durabilité
        non confirmée), puis le magasin reste lisible et redémarrable.
        """
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        real_fsync = os.fsync
        calls: list[int] = []

        def failing_fsync(fd):
            calls.append(fd)
            # 1 et 2 : contenu puis répertoire pour l'ancre. 3 : le JSONL,
            # c'est-à-dire la barrière de durabilité de la ligne DÉJÀ écrite.
            if len(calls) == 3:
                raise OSError(errno.EIO, "input/output error")
            return real_fsync(fd)

        with patch("rag_hermes.canonical_registry.os.fsync", failing_fsync):
            with self.assertRaises(CanonicalStoreError):
                registry.register(document(allowed_users=(), acl_version=2))

        revoked = registry.source("doc-1")
        assert revoked is not None
        self.assertEqual(revoked.allowed_users, ())
        reopened = CanonicalDocumentRegistry(self.store).source("doc-1")
        assert reopened is not None
        self.assertEqual(reopened.acl_version, 2)

    def test_a_broken_store_refuses_writes_as_well_as_reads(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        real_fdopen = os.fdopen

        def failing_fdopen(fd, mode="r", *args, **kwargs):
            if "a" in mode:
                raise OSError(errno.ENOSPC, "no space left on device")
            return real_fdopen(fd, mode, *args, **kwargs)

        with patch("rag_hermes.canonical_registry.os.fdopen", failing_fdopen):
            with self.assertRaises(CanonicalStoreError):
                registry.register(document(allowed_users=(), acl_version=2))

        with self.assertRaises(CanonicalStoreError):
            registry.register(document(allowed_users=(), acl_version=3))

    def test_reads_and_writes_do_not_deadlock_on_a_store_without_records(self) -> None:
        """Ordre des verrous : un lecteur ne doit jamais croiser un écrivain.

        Un magasin neuf (aucun enregistrement) est le cas où la lecture
        consultait l'ancre : si elle prenait le bail de transaction après le
        mutex d'instance, l'ordre inverse de l'écriture produisait un ABBA.
        """
        registry = CanonicalDocumentRegistry(self.store)
        self.assertIsNone(registry.source("doc-1"))
        barrier = threading.Barrier(3, timeout=10)

        def read_many():
            barrier.wait()
            for _ in range(40):
                registry.source("doc-1")

        def write_many():
            barrier.wait()
            for version in range(1, 6):
                registry.register(document(doc_version=version, content=f"v{version}"))

        with ThreadPoolExecutor(max_workers=2) as pool:
            reading = pool.submit(read_many)
            writing = pool.submit(write_many)
            barrier.wait()
            writing.result(timeout=20)
            reading.result(timeout=20)
        current = registry.source("doc-1")
        assert current is not None
        self.assertEqual(current.doc_version, 5)

    def test_a_cross_process_reader_of_an_empty_store_is_not_blocked_forever(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        started, outcome = ctx.Event(), ctx.Queue()
        registry = CanonicalDocumentRegistry(self.store)
        reader = ctx.Process(
            target=_read_in_another_process, args=(self.store, started, outcome)
        )
        reader.start()
        try:
            self.assertTrue(started.wait(30))
            registry.register(document())
            reader.join(15)
            self.assertFalse(reader.is_alive(), "cross-process reader never finished")
            self.assertEqual(reader.exitcode, 0)
        finally:
            if reader.is_alive():
                reader.terminate()
                reader.join(5)
        self.assertEqual(outcome.get(timeout=5), "accepted")

    def test_a_fresh_reader_racing_the_first_writer_is_not_refused(self) -> None:
        """Deux observations non synchronisées donneraient un refus fallacieux.

        Un processus neuf constate l'absence du JSONL ; un écrivain complet
        s'exécute ensuite. Si l'ancre était comparée sans reprendre
        l'observation sous le bail, il conclurait à une perte alors que le
        magasin n'a fait que grandir.
        """
        done: list[object] = []
        real_read_anchor = CanonicalDocumentRegistry._read_anchor

        def write_from_another_process_then_read(self, dir_fd):  # noqa: ANN001
            if not done:
                process = multiprocessing.get_context("spawn").Process(
                    target=_register_in_another_process, args=(self._store_dir,)
                )
                process.start()
                process.join(20)
                done.append(process.exitcode)
            return real_read_anchor(self, dir_fd)

        with patch.object(
            CanonicalDocumentRegistry, "_read_anchor", write_from_another_process_then_read
        ):
            reader = CanonicalDocumentRegistry(self.store)
        self.assertEqual(done, [0], "the racing writer failed")
        self.assertIsNotNone(reader.source("doc-1"))

    def test_a_forged_prefix_keeping_count_and_versions_is_refused(self) -> None:
        """L'ancre doit lier le CONTENU, pas seulement compte et versions."""
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        revoked = document(allowed_users=(), acl_version=2)
        registry.register(revoked)
        lines = registry.path.read_bytes().splitlines(keepends=True)
        self.assertEqual(len(lines), 2)

        # Même nombre de lignes, même acl_version ancrée, mais Bob revient.
        forged = json.dumps(
            {
                **json.loads(lines[-1]),
                "allowed_users": ["bob"],
            },
            sort_keys=True, separators=(",", ":"),
        ).encode("ascii") + b"\n"
        registry.path.write_bytes(lines[0] + forged)

        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_a_forged_record_APPENDED_after_the_anchor_is_refused(self) -> None:
        """L'ancre est publiée AVANT l'append, donc le fichier n'est jamais
        légitimement en avance : une ligne ajoutée sans ancre est refusée.

        Sans cette borne haute, une révocation se contourne en ajoutant une
        révision forgée à `acl_version` supérieure, sans toucher à l'ancre.
        """
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        registry.register(document(allowed_users=(), acl_version=2))
        anchor_before = registry.anchor_path.read_bytes()
        forged = json.dumps(
            _record_of(document(allowed_users=("bob",), acl_version=3)),
            sort_keys=True, separators=(",", ":"),
        ).encode("ascii") + b"\n"
        with registry.path.open("ab") as handle:
            handle.write(forged)

        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)
        self.assertEqual(registry.anchor_path.read_bytes(), anchor_before)

    def test_a_well_formed_empty_anchor_does_not_disable_the_guard(self) -> None:
        """Remettre une ancre vide ne doit pas valoir « pas d'ancre »."""
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        backup = registry.path.read_bytes()
        registry.register(document(allowed_users=(), acl_version=2))
        registry.path.write_bytes(backup)
        registry.anchor_path.write_text(
            json.dumps({
                "records": 0,
                "digest": hashlib.sha256(b"").hexdigest(),
                "documents": {},
            }),
            encoding="ascii",
        )

        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_deleted_history_is_not_recreated_after_revocation(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        registry.register(document(allowed_users=(), acl_version=2))
        registry.path.unlink()
        with self.assertRaises(RuntimeError):
            registry.source("doc-1")
        with self.assertRaises(RuntimeError):
            registry.register(document(allowed_users=("bob",), acl_version=1))
        self.assertFalse(registry.path.exists())

    def test_partial_last_line_fails_closed_until_repaired_offline(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document())
        with registry.path.open("ab") as handle:
            handle.write(b'{"document_id":"incomplete"')
        with self.assertRaises(CanonicalStoreError):
            registry.source("doc-1")
        with self.assertRaises(CanonicalStoreError):
            registry.register(document(doc_version=2))

    def test_content_change_at_equal_doc_version_is_refused(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        original = document(content="contenu initial")
        registry.register(original)
        before = registry.path.read_bytes()

        with self.assertRaisesRegex(ValueError, "doc_version"):
            registry.register(document(content="contenu remplacé", acl_version=2))

        self.assertEqual(registry.path.read_bytes(), before)
        self.assertEqual(registry.source("doc-1"), original)
        self.assertEqual(CanonicalDocumentRegistry(self.store).source("doc-1"), original)

    def test_source_uri_change_at_equal_doc_version_is_refused(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        original = document()
        registry.register(original)
        before = registry.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "doc_version"):
            registry.register(replace(original, source_uri="file:///docs/forged.md"))
        self.assertEqual(registry.path.read_bytes(), before)
        self.assertEqual(CanonicalDocumentRegistry(self.store).source("doc-1"), original)

    def test_acl_mutations_at_same_version_are_all_refused(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        original = document()
        registry.register(original)
        for field, value in (
            ("visibility", "public"),
            ("classification", 0),
            ("allowed_groups", ("ops",)),
            ("allowed_users", ("bob",)),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "acl_version"):
                    registry.register(replace(original, **{field: value}, doc_version=2))
        self.assertEqual(registry.source("doc-1"), original)

    def test_reimport_identical_and_independent_version_bumps_succeed(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        original = document()
        registry.register(original)
        registry.register(original)
        registry.register(replace(original, allowed_users=("bob",), acl_version=2))
        updated = replace(
            original, content="nouveau contenu", source_uri="file:///docs/new.md",
            allowed_users=("bob",), acl_version=2, doc_version=2,
        )
        registry.register(updated)
        self.assertEqual(CanonicalDocumentRegistry(self.store).source("doc-1"), updated)

    def test_replayed_acl_record_at_equal_version_refuses_startup(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",), acl_version=1))
        registry.register(document(allowed_users=(), acl_version=2))
        replay = json.loads(registry.path.read_text(encoding="utf-8").splitlines()[0])
        replay["acl_version"] = 2
        with registry.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(replay) + "\n")
        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_tampered_store_file_refuses_startup(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(doc_version=2))
        path = self.store / "canonical_documents.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            record["doc_version"] = 1
            handle.write(json.dumps(record, sort_keys=True) + "\n")

        with self.assertRaises(CanonicalStoreError):
            CanonicalDocumentRegistry(self.store)

    def test_stale_indexed_acl_version_is_reported_as_stale(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(acl_version=2))
        context = AuthorizationContext("alpha", "alice", (), 1)

        self.assertEqual(
            registry.authority.authorize("doc-1", 1, context), (False, "stale_acl_version")
        )
        self.assertEqual(
            registry.authority.authorize("doc-1", 2, context), (True, "allowed")
        )

    def test_authority_reflects_registrations_made_after_its_creation(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        authority = registry.authority
        self.assertIsNone(authority.policy_for("doc-1"))

        registry.register(document())

        self.assertIsNotNone(authority.policy_for("doc-1"))


class WriteThroughTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.registry = CanonicalDocumentRegistry(Path(self._tmp.name))
        self.repository = FakeRepository()
        self.write_through = CanonicalWriteThrough(self.repository, self.registry)

    def test_canonical_record_is_written_before_the_index(self) -> None:
        doc = document()
        order: list[str] = []
        original_register = self.registry.register
        original_replace = self.repository.replace_document

        def register(value):  # noqa: ANN001
            order.append("canonical")
            return original_register(value)

        def replace(value, chunks):  # noqa: ANN001
            order.append("index")
            return original_replace(value, chunks)

        self.registry.register = register  # type: ignore[method-assign]
        self.repository.replace_document = replace  # type: ignore[method-assign]

        result = self.write_through.replace_document(doc, chunk_document(doc))

        self.assertEqual(order, ["canonical", "index"])
        self.assertEqual(result.document_id, "doc-1")
        self.assertEqual(self.registry.source("doc-1"), doc)

    def test_a_refused_canonical_record_never_reaches_the_index(self) -> None:
        self.registry.register(document(tenant_id="alpha"))
        intruder = document(tenant_id="beta", owner_id="bob")
        self.repository.written.clear()

        with self.assertRaisesRegex(ValueError, "tenant"):
            self.write_through.replace_document(intruder, chunk_document(intruder))

        self.assertEqual(self.repository.written, [])

    def test_an_ownership_takeover_never_reaches_the_index(self) -> None:
        """Le dépôt refuse déjà la reprise, mais APRÈS l'écriture canonique."""
        self.registry.register(document(owner_id="alice"))
        self.repository.written.clear()

        with self.assertRaisesRegex(PermissionError, "owner_id"):
            self.write_through.replace_document(
                document(owner_id="bob", doc_version=2),
                chunk_document(document(owner_id="bob", doc_version=2)),
            )

        self.assertEqual(self.repository.written, [])
        stored = self.registry.source("doc-1")
        assert stored is not None
        self.assertEqual(stored.owner_id, "alice")

    def test_an_empty_replacement_is_refused_before_both_sides(self) -> None:
        doc = document(content="   ")
        with self.assertRaisesRegex(ValueError, "passage"):
            self.write_through.replace_document(doc, chunk_document(doc))

        self.assertEqual(self.repository.written, [])
        self.assertIsNone(self.registry.source("doc-1"))

    def test_search_is_delegated_unchanged(self) -> None:
        context = AuthorizationContext("alpha", "alice", (), 1)
        self.write_through.search("question", context=context, limit=4)
        self.assertEqual(self.repository.searches, [("question", 4)])

    def test_write_through_requires_the_exact_registry_type(self) -> None:
        class FauxRegistry:
            def register(self, document):  # noqa: ANN001
                return None

        with self.assertRaisesRegex(ValueError, "registry"):
            CanonicalWriteThrough(self.repository, FauxRegistry())  # type: ignore[arg-type]


class BarrierWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.registry = CanonicalDocumentRegistry(Path(self._tmp.name))

    def test_wrapper_builds_a_canonical_barrier_over_the_write_through(self) -> None:
        repository = FakeRepository()
        wrapped = wrap_repository_with_canonical_barrier(
            repository, self.registry, minimum_score=0.2
        )

        self.assertIs(type(wrapped), CanonicalAclSearch)
        self.assertEqual(wrapped.minimum_score, 0.2)
        inner = wrapped._ranked_search
        self.assertIs(type(inner), CanonicalWriteThrough)
        self.assertIs(inner._repository, repository)

    def test_imported_document_is_answerable_through_the_barrier(self) -> None:
        doc = document()
        chunks = chunk_document(doc)
        repository = FakeRepository([SearchResult(chunks[0], 0.9)])
        service = RagService(
            repository=wrap_repository_with_canonical_barrier(
                repository, self.registry, minimum_score=0.2
            ),
            top_k=1,
        )
        context = AuthorizationContext("alpha", "alice", (), 1)

        service.import_document(doc, context=context)
        trace = service.answer_with_trace("Comment installer Hermes ?", context=context)

        self.assertFalse(trace.response.abstained)
        self.assertEqual(
            [chunk.document_id for chunk in trace.cited_chunks], ["doc-1"]
        )

    def _service(self, repository) -> RagService:  # noqa: ANN001
        return RagService(
            repository=wrap_repository_with_canonical_barrier(
                repository, self.registry, minimum_score=0.2
            ),
            top_k=1,
        )

    def test_index_chunk_unknown_to_the_canonical_store_is_never_served(self) -> None:
        """Un point de l'index absent du registre est REFUSÉ (donc abstention).

        Le registre indexe par `document_id` ; un document inconnu de lui est
        traité comme non autorisé, jamais comme une preuve. La désynchronisation
        registre/index se lit donc en abstention, pas en erreur : c'est la
        direction sûre, et c'est une limite assumée (cf. docs/v1-canonical-acl.md).
        """
        doc = document("doc-fantome")
        repository = FakeRepository([SearchResult(chunk_document(doc)[0], 0.95)])
        service = self._service(repository)
        context = AuthorizationContext("alpha", "alice", (), 1)

        trace = service.answer_with_trace("question", context=context)

        self.assertTrue(trace.response.abstained)
        self.assertEqual(trace.retrieved_chunks, ())
        self.assertEqual(trace.cited_chunks, ())

    def test_cross_tenant_index_chunk_is_never_served_to_another_tenant(self) -> None:
        doc = document()
        foreign = document(
            "doc-2", tenant_id="beta", owner_id="bob", visibility="private"
        )
        repository = FakeRepository([SearchResult(chunk_document(foreign)[0], 0.99)])
        service = self._service(repository)
        context = AuthorizationContext("alpha", "alice", (), 1)
        service.import_document(doc, context=context)

        trace = service.answer_with_trace("question", context=context)

        self.assertTrue(trace.response.abstained)
        self.assertEqual(trace.retrieved_chunks, ())

    def test_payload_contradicting_the_canonical_policy_fails_closed(self) -> None:
        """Même version ACL, payload d'index plus permissif = panne de preuve."""
        doc = document()
        honest = chunk_document(doc)[0]
        forged = replace(honest, visibility="public", classification=0)
        repository = FakeRepository([SearchResult(forged, 0.95)])
        service = self._service(repository)
        context = AuthorizationContext("alpha", "alice", (), 1)
        service.import_document(doc, context=context)

        with self.assertRaisesRegex(CanonicalAclError, "conflicts"):
            service.answer_with_trace("question", context=context)

    def test_revocation_without_acl_version_bump_is_rejected_before_index_write(self) -> None:
        shared = document(visibility="private", allowed_users=("bob",))
        repository = FakeRepository([SearchResult(chunk_document(shared)[0], 0.9)])
        service = self._service(repository)
        owner = AuthorizationContext("alpha", "alice", (), 1)
        reader = AuthorizationContext("alpha", "bob", (), 1)
        service.import_document(shared, context=owner)
        original = self.registry.path.read_bytes()
        repository.written.clear()

        with self.assertRaisesRegex(ValueError, "acl_version"):
            service.import_document(document(allowed_users=()), context=owner)

        self.assertEqual(repository.written, [])
        self.assertEqual(self.registry.path.read_bytes(), original)
        policy = self.registry.authority.policy_for("doc-1")
        assert policy is not None
        self.assertEqual(policy.allowed_users, ("bob",))
        self.assertFalse(service.answer_with_trace("question", context=reader).response.abstained)

    def test_revocation_with_an_acl_version_bump_fails_closed_as_stale(self) -> None:
        """Chemin de révocation normal : l'index devient périmé, pas permissif."""
        shared = document(visibility="private", allowed_users=("bob",))
        repository = FakeRepository([SearchResult(chunk_document(shared)[0], 0.9)])
        service = self._service(repository)
        owner = AuthorizationContext("alpha", "alice", (), 1)
        reader = AuthorizationContext("alpha", "bob", (), 1)
        service.import_document(shared, context=owner)

        self.registry.register(
            document(visibility="private", allowed_users=(), acl_version=2)
        )

        # Le propriétaire reste autorisé par la politique canonique, donc la
        # barrière signale un index périmé plutôt qu'une abstention honnête.
        with self.assertRaisesRegex(CanonicalAclError, "stale"):
            service.answer_with_trace("question", context=owner)
        # Le lecteur révoqué n'est plus autorisé du tout : rien ne lui est servi.
        trace = service.answer_with_trace("question", context=reader)
        self.assertTrue(trace.response.abstained)
        self.assertEqual(trace.cited_chunks, ())

    def test_local_reader_waits_for_replacement_to_finish_before_search(self) -> None:
        initial = document(allowed_users=("bob",), acl_version=1)
        revised = document(allowed_users=(), acl_version=2)
        entered = threading.Event()
        release = threading.Event()
        searched = threading.Event()

        class BlockingRepository(FakeRepository):
            def replace_document(self, document, chunks):
                if document.acl_version == 2:
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError("test writer never released")
                self.results = [SearchResult(list(chunks)[0], 0.9)]
                return super().replace_document(document, chunks)

            def search(self, query, *, context, limit=10):
                searched.set()
                return super().search(query, context=context, limit=limit)

        repository = BlockingRepository()
        writer = RagService(repository=wrap_repository_with_canonical_barrier(
            repository, self.registry, minimum_score=0.2,
        ))
        reader_registry = CanonicalDocumentRegistry(Path(self._tmp.name))
        reader = RagService(repository=wrap_repository_with_canonical_barrier(
            repository, reader_registry, minimum_score=0.2,
        ))
        owner = AuthorizationContext("alpha", "alice", (), 1)
        writer.import_document(initial, context=owner)
        searched.clear()
        with ThreadPoolExecutor(max_workers=2) as pool:
            writing = pool.submit(writer.import_document, revised, context=owner)
            self.assertTrue(entered.wait(5))
            reading = pool.submit(reader.answer_with_trace, "Hermes", context=owner)
            try:
                self.assertFalse(searched.wait(0.15), "reader searched mid-replacement")
            finally:
                release.set()
            writing.result(timeout=5)
            answer = reading.result(timeout=5)
        self.assertFalse(answer.response.abstained)
        self.assertEqual(answer.cited_chunks[0].acl_version, 2)

    def test_local_writer_waits_until_generation_and_citation_finish(self) -> None:
        initial = document(allowed_users=("bob",), acl_version=1)
        revised = document(allowed_users=(), acl_version=2)
        generating = threading.Event()
        release = threading.Event()
        wrote = threading.Event()

        class RecordingRepository(FakeRepository):
            def replace_document(self, document, chunks):
                if document.acl_version == 2:
                    wrote.set()
                return super().replace_document(document, chunks)

        repository = RecordingRepository([SearchResult(chunk_document(initial)[0], 0.9)])
        writer = self._service(repository)
        owner = AuthorizationContext("alpha", "alice", (), 1)
        writer.import_document(initial, context=owner)
        reader_registry = CanonicalDocumentRegistry(Path(self._tmp.name))

        def generator(question, evidence):
            generating.set()
            if not release.wait(5):
                raise TimeoutError("test generator never released")
            return "Réponse [S1]"

        reader = RagService(repository=wrap_repository_with_canonical_barrier(
            repository, reader_registry, minimum_score=0.2,
        ), generator=generator)
        with ThreadPoolExecutor(max_workers=2) as pool:
            reading = pool.submit(reader.answer_with_trace, "Hermes", context=owner)
            self.assertTrue(generating.wait(5))
            writing = pool.submit(writer.import_document, revised, context=owner)
            try:
                self.assertFalse(wrote.wait(0.15), "writer mutated index during generation")
            finally:
                release.set()
            answer = reading.result(timeout=5)
            writing.result(timeout=5)
        self.assertEqual(answer.cited_chunks[0].acl_version, 1)
        self.assertTrue(wrote.is_set())
        policy = self.registry.authority.policy_for("doc-1")
        assert policy is not None
        self.assertEqual(policy.acl_version, 2)

    def test_wsgi_delivery_after_revocation_is_not_retroactively_cancelled(self) -> None:
        initial = document(allowed_users=("bob",), acl_version=1)
        repository = FakeRepository([SearchResult(chunk_document(initial)[0], 0.9)])
        service = self._service(repository)
        service.import_document(initial, context=AuthorizationContext("alpha", "alice", (), 1))
        class BobAuthenticator:
            def authenticate(self, environ):
                return AuthorizationContext("alpha", "bob", (), 1)

        app = make_app(service, authenticator=BobAuthenticator())
        body = json.dumps({"question": "Hermes"}).encode("utf-8")
        statuses = []
        response = app({
            "REQUEST_METHOD": "POST", "PATH_INFO": "/api/questions",
            "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/json",
            "wsgi.input": BytesIO(body), "HTTP_HOST": "localhost:8080",
        }, lambda status, headers: statuses.append(status))
        self.registry.register(document(allowed_users=(), acl_version=2))
        delivered = json.loads(b"".join(response))
        self.assertEqual(statuses, ["200 OK"])
        self.assertFalse(delivered["abstained"])
        self.assertEqual(delivered["citations"][0]["document_id"], "doc-1")
        # A new request after the completed revocation does not cite it.
        self.assertTrue(service.answer_with_trace(
            "Hermes", context=AuthorizationContext("alpha", "bob", (), 1)
        ).response.abstained)

    def test_direct_barrier_search_also_waits_for_a_replacement(self) -> None:
        """Evaluation paths call `search()` without going through the service."""
        initial = document(allowed_users=("bob",), acl_version=1)
        revised = document(allowed_users=(), acl_version=2)
        entered, release, searched = (threading.Event() for _ in range(3))

        class BlockingRepository(FakeRepository):
            def replace_document(self, document, chunks):
                if document.acl_version == 2:
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError("test writer never released")
                self.results = [SearchResult(list(chunks)[0], 0.9)]
                return super().replace_document(document, chunks)

            def search(self, query, *, context, limit=10):
                searched.set()
                return super().search(query, context=context, limit=limit)

        repository = BlockingRepository()
        writer = self._service(repository)
        owner = AuthorizationContext("alpha", "alice", (), 1)
        writer.import_document(initial, context=owner)
        searched.clear()
        barrier = wrap_repository_with_canonical_barrier(
            repository, CanonicalDocumentRegistry(Path(self._tmp.name)), minimum_score=0.2,
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            writing = pool.submit(writer.import_document, revised, context=owner)
            self.assertTrue(entered.wait(5))
            reading = pool.submit(barrier.search, "Hermes", context=owner, limit=1)
            try:
                self.assertFalse(searched.wait(0.15), "direct search ran mid-replacement")
            finally:
                release.set()
            writing.result(timeout=5)
            results = reading.result(timeout=5)
        self.assertEqual([result.chunk.acl_version for result in results], [2])


if __name__ == "__main__":
    unittest.main()
