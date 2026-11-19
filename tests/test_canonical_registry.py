"""Registre documentaire canonique de la V1 (SEC-01) : tests CPU.

Ces tests éprouvent l'autorité ACL canonique *locale* alimentée par les imports
authentifiés, indépendante de l'index Qdrant, et son branchement en barrière de
lecture. Aucun Qdrant, aucun modèle, aucun GPU.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.canonical_registry import (
    CanonicalDocumentRegistry,
    CanonicalWriteThrough,
    wrap_repository_with_canonical_barrier,
)
from rag_hermes.ingestion import Document, chunk_document
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

    def test_revocation_at_equal_versions_is_accepted_and_overwrites(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(allowed_users=("bob",)))
        registry.register(document(allowed_users=()))

        policy = registry.authority.policy_for("doc-1")
        assert policy is not None
        self.assertEqual(policy.allowed_users, ())

    def test_tampered_store_file_refuses_startup(self) -> None:
        registry = CanonicalDocumentRegistry(self.store)
        registry.register(document(doc_version=2))
        path = self.store / "canonical_documents.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            record["doc_version"] = 1
            handle.write(json.dumps(record, sort_keys=True) + "\n")

        with self.assertRaisesRegex(ValueError, "doc_version"):
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

    def test_canonical_revocation_at_equal_version_is_never_served(self) -> None:
        """Révoquer dans le registre sans réindexer rend le payload contradictoire.

        L'index garde `allowed_users=("bob",)` que le registre a retiré. Les
        deux issues sont sûres mais DIFFÉRENTES, parce que la comparaison du
        payload à la politique vient APRÈS l'autorisation du demandeur :
        - le lecteur révoqué est refusé par la politique canonique -> abstention ;
        - le propriétaire, lui, est autorisé, donc la divergence de payload est
          atteinte et échoue fermé jusqu'à réindexation (déni de service assumé).
        """
        shared = document(visibility="private", allowed_users=("bob",))
        repository = FakeRepository([SearchResult(chunk_document(shared)[0], 0.9)])
        service = self._service(repository)
        owner = AuthorizationContext("alpha", "alice", (), 1)
        reader = AuthorizationContext("alpha", "bob", (), 1)
        service.import_document(shared, context=owner)

        self.assertFalse(
            service.answer_with_trace("question", context=reader).response.abstained
        )

        self.registry.register(document(visibility="private", allowed_users=()))

        trace = service.answer_with_trace("question", context=reader)
        self.assertTrue(trace.response.abstained)
        self.assertEqual(trace.cited_chunks, ())
        with self.assertRaisesRegex(CanonicalAclError, "conflicts"):
            service.answer_with_trace("question", context=owner)

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


if __name__ == "__main__":
    unittest.main()
