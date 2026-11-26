"""Découpage A de l'issue #71 : état canonique persistant `active`/`inactive`.

Tranche CPU STRICTE : schéma JSONL versionné (migration sans réinterprétation),
machine à états `active → inactive` par transition dédiée interne, refus de
réactivation implicite, refus de lecture/génération V1, ancre versionnée et
cas fail-closed (ancre en avance / en retard, durabilité). AUCUNE mutation
Qdrant, AUCUN endpoint, AUCUNE restauration ici (tranches B/C).

Deux familles de tests, toutes deux nécessaires :
- la méthode interne `mark_inactive` prouve le VRAI chemin d'écriture persisté ;
- des lignes JSONL/ancres FORGÉES à la main éprouvent le décodeur contre un
  historique corrompu ou hostile.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.canonical_registry import (
    CanonicalDocumentRegistry,
    CanonicalStoreError,
    CanonicalWriteThrough,
    _LiveCanonicalAclAuthority,
    _validated_anchor,
    bootstrap_canonical_anchor,
    wrap_repository_with_canonical_barrier,
    _ANCHOR_FILENAME,
    _STORE_FILENAME,
)
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.retrieval import CanonicalAclError, SearchResult
from rag_hermes.service import RagService


_LEGACY_KEYS = (
    "document_id",
    "content",
    "tenant_id",
    "visibility",
    "owner_id",
    "allowed_groups",
    "allowed_users",
    "classification",
    "doc_version",
    "acl_version",
    "source_uri",
)


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
    allowed_users: tuple[str, ...] = ("alice",),
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


def _legacy_record(doc: Document) -> dict:
    """La projection 11-clés d'AVANT ce lot (aucune clé `state`)."""
    return {
        "document_id": doc.document_id,
        "content": doc.content,
        "tenant_id": doc.tenant_id,
        "visibility": doc.visibility,
        "owner_id": doc.owner_id,
        "allowed_groups": list(doc.allowed_groups),
        "allowed_users": list(doc.allowed_users),
        "classification": doc.classification,
        "doc_version": doc.doc_version,
        "acl_version": doc.acl_version,
        "source_uri": doc.source_uri,
    }


def _modern_record(doc: Document, *, state: str = "active") -> dict:
    record = _legacy_record(doc)
    record["state"] = state
    return record


def _line(record: dict) -> bytes:
    return (
        json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("ascii")


def _write_store(store_dir: Path, lines: list[bytes], anchor: dict) -> None:
    """Fabriquer un magasin JSONL + ancre à la main (historique forgé)."""
    (store_dir / _STORE_FILENAME).write_bytes(b"".join(lines))
    os.chmod(store_dir / _STORE_FILENAME, 0o600)
    (store_dir / _ANCHOR_FILENAME).write_bytes(
        json.dumps(anchor, sort_keys=True, separators=(",", ":")).encode("ascii")
    )
    os.chmod(store_dir / _ANCHOR_FILENAME, 0o600)


def _digest(lines: list[bytes]) -> str:
    running = hashlib.sha256()
    for line in lines:
        running.update(line)
    return running.hexdigest()


def _legacy_anchor(docs: list[Document], lines: list[bytes]) -> dict:
    return {
        "records": len(lines),
        "digest": _digest(lines),
        "documents": {
            d.document_id: {"doc_version": d.doc_version, "acl_version": d.acl_version}
            for d in docs
        },
    }


class _StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)

    def registry(self) -> CanonicalDocumentRegistry:
        return CanonicalDocumentRegistry(self.store)

    def raw_lines(self) -> list[str]:
        return (self.store / _STORE_FILENAME).read_text("utf-8").splitlines()


class SchemaVersioningTests(_StoreCase):
    def test_new_active_write_always_carries_state_key(self) -> None:
        self.registry().register(document())
        line = json.loads(self.raw_lines()[0])
        self.assertIn("state", line)
        self.assertEqual(line["state"], "active")
        self.assertEqual(set(line), set(_LEGACY_KEYS) | {"state"})

    def test_legacy_eleven_key_record_reads_as_active(self) -> None:
        doc = document()
        lines = [_line(_legacy_record(doc))]
        _write_store(self.store, lines, _legacy_anchor([doc], lines))
        reg = self.registry()
        got = reg.source(doc.document_id)
        self.assertIsNotNone(got)
        self.assertEqual(got.state, "active")

    def test_eleven_key_after_twelve_key_same_doc_is_refused(self) -> None:
        """Monotonie de schéma : pas de retour à 11 clés (clé perdue = attaque)."""
        doc = document()
        l1 = _line(_modern_record(doc, state="active"))
        l2 = _line(_legacy_record(replace(doc, doc_version=2)))
        lines = [l1, l2]
        anchor = {
            "schema_version": 2,
            "records": 2,
            "digest": _digest(lines),
            "documents": {
                doc.document_id: {"doc_version": 2, "acl_version": 1, "state": "active"}
            },
        }
        _write_store(self.store, lines, anchor)
        with self.assertRaises(CanonicalStoreError):
            self.registry().source(doc.document_id)


class MarkInactiveStateMachineTests(_StoreCase):
    def test_mark_inactive_hides_from_source_and_policy(self) -> None:
        reg = self.registry()
        reg.register(document())
        reg.mark_inactive("doc-1", owner_id="alice")
        self.assertIsNone(reg.source("doc-1"))
        authority = _LiveCanonicalAclAuthority(reg)
        self.assertIsNone(authority.policy_for("doc-1"))

    def test_mark_inactive_bumps_acl_version_and_preserves_identity(self) -> None:
        reg = self.registry()
        reg.register(document(doc_version=3, acl_version=5, content="secret privé"))
        reg.mark_inactive("doc-1", owner_id="alice")
        masked = reg._documents["doc-1"]  # vue interne (y compris inactive)
        self.assertEqual(masked.state, "inactive")
        self.assertEqual(masked.acl_version, 6)
        self.assertEqual(masked.doc_version, 3)
        self.assertEqual(masked.content, "secret privé")
        self.assertEqual(masked.owner_id, "alice")
        self.assertEqual(masked.tenant_id, "alpha")

    def test_mark_inactive_wrong_owner_is_refused(self) -> None:
        reg = self.registry()
        reg.register(document(owner_id="alice"))
        with self.assertRaises(PermissionError):
            reg.mark_inactive("doc-1", owner_id="bob")
        self.assertIsNotNone(reg.source("doc-1"))

    def test_mark_inactive_unknown_document_is_refused(self) -> None:
        reg = self.registry()
        reg.register(document())
        with self.assertRaises((ValueError, CanonicalStoreError)):
            reg.mark_inactive("absent", owner_id="alice")

    def test_second_mark_inactive_is_refused(self) -> None:
        reg = self.registry()
        reg.register(document())
        reg.mark_inactive("doc-1", owner_id="alice")
        with self.assertRaises((ValueError, CanonicalStoreError)):
            reg.mark_inactive("doc-1", owner_id="alice")

    def test_ordinary_import_cannot_reactivate_inactive(self) -> None:
        reg = self.registry()
        reg.register(document())
        reg.mark_inactive("doc-1", owner_id="alice")
        with self.assertRaises((ValueError, PermissionError, CanonicalStoreError)):
            reg.register(document(doc_version=9, acl_version=9))
        self.assertIsNone(reg.source("doc-1"))

    def test_inactive_survives_a_fresh_registry_restart(self) -> None:
        self.registry().register(document())
        self.registry().mark_inactive("doc-1", owner_id="alice")
        # Instance neuve = redémarrage : rien observé en mémoire, tout rejoué.
        fresh = self.registry()
        self.assertIsNone(fresh.source("doc-1"))
        self.assertIsNone(_LiveCanonicalAclAuthority(fresh).policy_for("doc-1"))

    def test_other_documents_stay_active(self) -> None:
        reg = self.registry()
        reg.register(document("doc-1"))
        reg.register(document("doc-2"))
        reg.mark_inactive("doc-1", owner_id="alice")
        self.assertIsNone(reg.source("doc-1"))
        self.assertIsNotNone(reg.source("doc-2"))


class ForgedReactivationTests(_StoreCase):
    def test_forged_active_line_after_inactive_without_anchor_is_unavailable(self) -> None:
        reg = self.registry()
        reg.register(document())
        reg.mark_inactive("doc-1", owner_id="alice")
        # Append hostile d'une ligne active SANS mettre l'ancre à jour.
        forged = _line(_modern_record(document(doc_version=9, acl_version=9), state="active"))
        with open(self.store / _STORE_FILENAME, "ab") as handle:
            handle.write(forged)
        # Le fichier est désormais en avance sur l'ancre → incohérent : le
        # magasin devient INDISPONIBLE dès le rechargement (échec fermé), donc
        # la ligne active forgée n'est jamais servie.
        with self.assertRaises(CanonicalStoreError):
            self.registry().source("doc-1")

    def test_forged_active_line_in_replayed_history_is_refused(self) -> None:
        doc = document()
        l1 = _line(_modern_record(doc, state="active"))
        l2 = _line(_modern_record(replace(doc, acl_version=2), state="inactive"))
        l3 = _line(_modern_record(replace(doc, acl_version=3), state="active"))
        lines = [l1, l2, l3]
        anchor = {
            "schema_version": 2,
            "records": 3,
            "digest": _digest(lines),
            "documents": {
                doc.document_id: {"doc_version": 1, "acl_version": 3, "state": "active"}
            },
        }
        _write_store(self.store, lines, anchor)
        with self.assertRaises(CanonicalStoreError):
            self.registry().source(doc.document_id)


class AnchorVersioningTests(_StoreCase):
    def test_anchor_is_modern_and_records_state_after_write(self) -> None:
        reg = self.registry()
        reg.register(document())
        reg.mark_inactive("doc-1", owner_id="alice")
        anchor = json.loads((self.store / _ANCHOR_FILENAME).read_text("utf-8"))
        self.assertEqual(anchor.get("schema_version"), 2)
        self.assertEqual(anchor["documents"]["doc-1"]["state"], "inactive")

    def test_legacy_anchor_with_legacy_history_still_loads(self) -> None:
        doc = document()
        lines = [_line(_legacy_record(doc))]
        _write_store(self.store, lines, _legacy_anchor([doc], lines))
        self.assertIsNotNone(self.registry().source(doc.document_id))

    def test_legacy_anchor_cannot_attest_modern_history(self) -> None:
        doc = document()
        lines = [_line(_modern_record(doc, state="inactive"))]
        # Ancre au FORMAT legacy (pas de schema_version, marques sans state).
        _write_store(self.store, lines, _legacy_anchor([doc], lines))
        with self.assertRaises(CanonicalStoreError):
            self.registry().source(doc.document_id)

    def test_validated_anchor_rejects_unknown_state(self) -> None:
        payload = {
            "schema_version": 2,
            "records": 1,
            "digest": "0" * 64,
            "documents": {"d": {"doc_version": 1, "acl_version": 1, "state": "frozen"}},
        }
        with self.assertRaises(ValueError):
            _validated_anchor(payload)

    def test_validated_anchor_rejects_bool_schema_version(self) -> None:
        payload = {
            "schema_version": True,
            "records": 1,
            "digest": "0" * 64,
            "documents": {"d": {"doc_version": 1, "acl_version": 1, "state": "active"}},
        }
        with self.assertRaises(ValueError):
            _validated_anchor(payload)

    def test_validated_anchor_rejects_modern_mark_without_version_key(self) -> None:
        payload = {
            "schema_version": 2,
            "records": 1,
            "digest": "0" * 64,
            "documents": {"d": {"doc_version": 1, "state": "active"}},
        }
        with self.assertRaises(ValueError):
            _validated_anchor(payload)

    def test_validated_anchor_rejects_state_on_legacy_format(self) -> None:
        # Format legacy (sans schema_version) mais marque porteuse de state :
        # un format mixte incohérent doit échouer, pas être deviné.
        payload = {
            "records": 1,
            "digest": "0" * 64,
            "documents": {"d": {"doc_version": 1, "acl_version": 1, "state": "active"}},
        }
        with self.assertRaises(ValueError):
            _validated_anchor(payload)


class AnchorAheadInactiveTests(_StoreCase):
    def test_anchor_ahead_of_inactive_history_is_unavailable_not_readable(self) -> None:
        """Ancre en avance (crash entre publication d'ancre et append) : jamais lisible."""
        doc = document()
        active_line = _line(_modern_record(doc, state="active"))
        inactive_line = _line(_modern_record(replace(doc, acl_version=2), state="inactive"))
        lines_on_disk = [active_line]  # l'append de la ligne inactive n'a pas eu lieu
        anchor = {
            "schema_version": 2,
            "records": 2,
            "digest": _digest([active_line, inactive_line]),
            "documents": {
                doc.document_id: {"doc_version": 1, "acl_version": 2, "state": "inactive"}
            },
        }
        _write_store(self.store, lines_on_disk, anchor)
        with self.assertRaises(CanonicalStoreError):
            self.registry().source(doc.document_id)


class BootstrapStateTests(_StoreCase):
    """Migration d'ancre (req #4) : legacy versions-seules OK ; moderne exige
    état + digest, et aucun outil ne contourne l'état `inactive`."""

    def test_legacy_history_migrates_with_versions_only_attestation(self) -> None:
        # Vrai historique legacy : lignes 11-clés, SANS ancre. L'attestation
        # versions-seules (format d'avant ce lot) suffit et publie une ancre.
        doc = document()
        (self.store / _STORE_FILENAME).write_bytes(_line(_legacy_record(doc)))
        os.chmod(self.store / _STORE_FILENAME, 0o600)
        bootstrap_canonical_anchor(
            self.store,
            {"records": 1, "documents": {"doc-1": {"doc_version": 1, "acl_version": 1}}},
        )
        self.assertTrue((self.store / _ANCHOR_FILENAME).exists())
        self.assertIsNotNone(self.registry().source("doc-1"))

    def test_modern_history_without_state_attestation_is_refused(self) -> None:
        reg = self.registry()
        reg.register(document())
        reg.mark_inactive("doc-1", owner_id="alice")
        (self.store / _ANCHOR_FILENAME).unlink()
        digest = hashlib.sha256((self.store / _STORE_FILENAME).read_bytes()).hexdigest()
        with self.assertRaises(CanonicalStoreError) as caught:
            bootstrap_canonical_anchor(
                self.store,
                {
                    "records": 2,
                    "digest": digest,
                    "documents": {"doc-1": {"doc_version": 1, "acl_version": 2}},
                },
            )
        self.assertIn("requires document state", str(caught.exception))

    def test_modern_history_without_digest_is_refused(self) -> None:
        reg = self.registry()
        reg.register(document())
        reg.mark_inactive("doc-1", owner_id="alice")
        (self.store / _ANCHOR_FILENAME).unlink()
        with self.assertRaises(CanonicalStoreError) as caught:
            bootstrap_canonical_anchor(
                self.store,
                {
                    "records": 2,
                    "documents": {
                        "doc-1": {"doc_version": 1, "acl_version": 2, "state": "inactive"}
                    },
                },
            )
        self.assertIn("requires an attested digest", str(caught.exception))

    def test_modern_history_wrong_digest_is_refused(self) -> None:
        reg = self.registry()
        reg.register(document())
        reg.mark_inactive("doc-1", owner_id="alice")
        (self.store / _ANCHOR_FILENAME).unlink()
        with self.assertRaises(CanonicalStoreError) as caught:
            bootstrap_canonical_anchor(
                self.store,
                {
                    "records": 2,
                    "digest": "0" * 64,
                    "documents": {
                        "doc-1": {"doc_version": 1, "acl_version": 2, "state": "inactive"}
                    },
                },
            )
        self.assertIn("digest does not match", str(caught.exception))

    def test_bootstrap_cannot_reactivate_an_inactive_document(self) -> None:
        # Attester l'état `active` d'un document RÉELLEMENT inactif (tentative de
        # déschuchotage via la migration) doit diverger et être refusé.
        reg = self.registry()
        reg.register(document())
        reg.mark_inactive("doc-1", owner_id="alice")
        (self.store / _ANCHOR_FILENAME).unlink()
        digest = hashlib.sha256((self.store / _STORE_FILENAME).read_bytes()).hexdigest()
        with self.assertRaises(CanonicalStoreError) as caught:
            bootstrap_canonical_anchor(
                self.store,
                {
                    "records": 2,
                    "digest": digest,
                    "documents": {
                        "doc-1": {"doc_version": 1, "acl_version": 2, "state": "active"}
                    },
                },
            )
        self.assertIn("does not match the operator attestation", str(caught.exception))
        # Bootstrap refusé = aucune ancre publiée : le magasin reste INDISPONIBLE
        # (échec fermé), donc le document inactif n'est jamais servi réactivé.
        with self.assertRaises(CanonicalStoreError):
            self.registry()


class _FakeRepository:
    """Double fidèle : sert un résultat MÊME pour un doc masqué (tombstone:false)
    côté index, pour prouver que c'est la barrière CANONIQUE qui refuse."""

    def __init__(self, results: list[SearchResult] | None = None) -> None:
        self.results = results or []

    def replace_document(self, document, chunks):  # noqa: ANN001
        materialized = list(chunks)

        class _Result:
            document_id = document.document_id
            chunk_count = len(materialized)

        return _Result()

    def search(self, query, *, context, limit=10):  # noqa: ANN001
        return self.results[:limit]


class V1ReadBarrierInventoryTests(_StoreCase):
    """Inventaire : TOUT chemin de lecture V1 du registre refuse un doc inactive.

    Chemins énumérés (consommateurs vivants de l'autorité canonique) :
    `registry.source`, `registry.authority.policy_for`, `registry.authority
    .authorize`, et la barrière de bout en bout `CanonicalAclSearch` via
    `RagService.answer_with_trace` (recherche, récupération, citation, réponse).
    Les voies G1 à snapshot FIGÉ sont hors périmètre (tranche B/C).
    """

    def test_registry_read_paths_all_refuse_inactive(self) -> None:
        reg = self.registry()
        reg.register(document(acl_version=1))
        reg.mark_inactive("doc-1", owner_id="alice")
        context = AuthorizationContext("alpha", "alice", (), 1)
        # source()
        self.assertIsNone(reg.source("doc-1"))
        # policy_for() (délègue à source)
        self.assertIsNone(reg.authority.policy_for("doc-1"))
        # authorize() → inconnu (pas une abstention « stale »)
        allowed, reason = reg.authority.authorize("doc-1", 2, context)
        self.assertFalse(allowed)
        self.assertEqual(reason, "unknown_document")

    def test_masked_document_is_not_answerable_through_the_barrier(self) -> None:
        reg = self.registry()
        doc = document()
        repository = _FakeRepository([SearchResult(chunk_document(doc)[0], 0.9)])
        service = RagService(
            repository=wrap_repository_with_canonical_barrier(
                repository, reg, minimum_score=0.2
            ),
            top_k=1,
        )
        context = AuthorizationContext("alpha", "alice", (), 1)
        service.import_document(doc, context=context)
        # Avant masquage : répondable et cité.
        before = service.answer_with_trace("Comment installer Hermes ?", context=context)
        self.assertFalse(before.response.abstained)
        self.assertEqual([c.document_id for c in before.cited_chunks], ["doc-1"])

        reg.mark_inactive("doc-1", owner_id="alice")

        # Après masquage : aucune nouvelle recherche/réponse/citation ne livre le
        # document, MÊME si le point d'index reste candidat (tombstone:false).
        after = service.answer_with_trace("Comment installer Hermes ?", context=context)
        self.assertTrue(after.response.abstained)
        self.assertEqual(after.retrieved_chunks, ())
        self.assertEqual(after.cited_chunks, ())


if __name__ == "__main__":
    unittest.main()
