"""CPU tracer for a G1 candidate path; no model or GPU is required."""

import unittest
from dataclasses import replace

from rag_hermes.acl import AuthorizationContext
from rag_hermes.acl_authority import AclPolicy, CanonicalAclAuthority
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_filter import build_qdrant_filter
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_store import chunk_to_point
from rag_hermes import retrieval
from rag_hermes.service import RagService


class FakeRankedSearch:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def search(self, question, *, context, limit):
        self.calls.append((question, context, limit))
        return self.results[:limit]


def source_document(document_id, text):
    return Document(
        document_id=document_id,
        content=text,
        tenant_id="alpha",
        visibility="private",
        owner_id="alice",
        allowed_groups=(),
        allowed_users=(),
        classification=1,
        doc_version=1,
        source_uri=f"file:///docs/{document_id}.md",
    )


def candidate(document_id, text, *, score):
    return retrieval.SearchResult(chunk_document(source_document(document_id, text))[0], score)


class G1CanonicalBridgeTests(unittest.TestCase):
    def test_stale_high_ranked_candidate_never_reaches_generator_or_citation(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        authority = CanonicalAclAuthority({
            "stale": AclPolicy("alpha", "private", "alice", (), (), 1, 2),
            "allowed": AclPolicy("alpha", "private", "alice", (), (), 1, 1),
        })
        ranked = FakeRankedSearch([
            candidate("stale", "Ancienne instruction privee", score=0.99),
            candidate("allowed", "Installez Hermes avec pipx", score=0.88),
        ])
        seen = []

        def generate(question, evidence):
            seen.extend(chunk.document_id for chunk in evidence)
            return "Utilisez pipx [S1]."

        bridge = retrieval.CanonicalAclSearch(
            ranked, authority,
            source=lambda doc_id: {"allowed": source_document(
                "allowed", "Installez Hermes avec pipx"
            )}.get(doc_id),
        )
        service = RagService(repository=bridge, generator=generate, top_k=2)
        trace = service.answer_with_trace("Comment installer Hermes ?", context=context)

        self.assertEqual(ranked.calls, [
            ("Comment installer Hermes ?", context, 2),
            ("Comment installer Hermes ?", context, 4),
        ])
        self.assertEqual(seen, ["allowed"])
        self.assertEqual([c.document_id for c in trace.retrieved_chunks], ["allowed"])
        self.assertEqual([c.document_id for c in trace.cited_chunks], ["allowed"])
        self.assertEqual([c.document_id for c in trace.response.citations], ["allowed"])
        self.assertFalse(trace.response.abstained)

    def test_same_version_but_conflicting_acl_payload_fails_closed(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        authority = CanonicalAclAuthority({
            "allowed": AclPolicy("alpha", "private", "alice", (), (), 1, 1),
        })
        original = candidate("allowed", "Document prive", score=0.9)
        forged = replace(
            original,
            chunk=replace(original.chunk, visibility="public", classification=0),
        )
        called = []

        def generate(question, evidence):
            called.append(evidence)
            return "Document prive [S1]."

        service = RagService(
            repository=retrieval.CanonicalAclSearch(FakeRankedSearch([forged]), authority),
            generator=generate,
        )
        with self.assertRaisesRegex(PermissionError, "ACL payload"):
            service.answer("Document ?", context=context)
        self.assertEqual(called, [])

    def test_forged_text_uri_or_revision_cannot_reach_generator_or_citation(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        authority = CanonicalAclAuthority({
            "allowed": AclPolicy("alpha", "private", "alice", (), (), 1, 1),
        })
        trusted = source_document("allowed", "Texte canonique")
        original = candidate("allowed", "Texte canonique", score=0.9)
        for fields in (
            {"text": "Secret du tenant beta"},
            {"source_uri": "file:///tenant-beta/secret.md"},
            {"doc_version": 2},
        ):
            with self.subTest(fields=fields):
                forged = replace(original, chunk=replace(original.chunk, **fields))
                calls = []
                service = RagService(
                    repository=retrieval.CanonicalAclSearch(
                        FakeRankedSearch([forged]), authority,
                        source=lambda document_id: trusted,
                    ),
                    generator=lambda question, evidence: calls.append(evidence) or "Fuite [S1]",
                )
                with self.assertRaisesRegex(PermissionError, "provenance"):
                    service.answer("Question ?", context=context)
                self.assertEqual(calls, [])

    def test_without_independent_canonical_source_fails_closed(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        authority = CanonicalAclAuthority({
            "allowed": AclPolicy("alpha", "private", "alice", (), (), 1, 1),
        })
        calls = []
        service = RagService(
            repository=retrieval.CanonicalAclSearch(
                FakeRankedSearch([candidate("allowed", "Texte", score=0.9)]), authority
            ),
            generator=lambda question, evidence: calls.append(evidence) or "Fuite [S1]",
        )
        with self.assertRaisesRegex(PermissionError, "trusted provenance"):
            service.answer("Question ?", context=context)
        self.assertEqual(calls, [])

    def test_denied_conflicting_candidate_cannot_block_authorized_answer(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        authority = CanonicalAclAuthority({
            "foreign": AclPolicy("beta", "private", "bob", (), (), 1, 1),
            "allowed": AclPolicy("alpha", "private", "alice", (), (), 1, 1),
        })
        forged = candidate("foreign", "Autre tenant", score=0.99)
        seen = []
        service = RagService(
            repository=retrieval.CanonicalAclSearch(FakeRankedSearch([
                forged, candidate("allowed", "Source valide", score=0.8)
            ]), authority, source=lambda doc_id: {"allowed": source_document(
                "allowed", "Source valide"
            )}.get(doc_id)),
            generator=lambda question, evidence: seen.extend(evidence) or "Valide [S1]",
            top_k=2,
        )
        response = service.answer("Question ?", context=context)
        self.assertEqual([chunk.document_id for chunk in seen], ["allowed"])
        self.assertEqual([citation.document_id for citation in response.citations], ["allowed"])

    def test_top_one_retries_past_denied_candidate(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        authority = CanonicalAclAuthority({
            "foreign": AclPolicy("beta", "private", "bob", (), (), 1, 1),
            "allowed": AclPolicy("alpha", "private", "alice", (), (), 1, 1),
        })
        ranked = FakeRankedSearch([
            candidate("foreign", "Interdit", score=0.99),
            candidate("allowed", "Source valide", score=0.8),
        ])
        service = RagService(
            repository=retrieval.CanonicalAclSearch(
                ranked, authority,
                source=lambda doc_id: {"allowed": source_document(
                    "allowed", "Source valide"
                )}.get(doc_id),
            ),
            generator=lambda question, evidence: "Valide [S1]",
            top_k=1,
        )
        response = service.answer("Question ?", context=context)
        self.assertEqual([call[2] for call in ranked.calls], [1, 2])
        self.assertEqual([citation.document_id for citation in response.citations], ["allowed"])

    def test_top_one_widens_past_below_threshold_candidate(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        authority = CanonicalAclAuthority({
            "low": AclPolicy("alpha", "private", "alice", (), (), 1, 1),
            "allowed": AclPolicy("alpha", "private", "alice", (), (), 1, 1),
        })
        low = replace(candidate("low", "Hors seuil", score=0.9), threshold_score=0.1)
        good = replace(candidate("allowed", "Source valide", score=0.8), threshold_score=0.9)
        ranked = FakeRankedSearch([low, good])
        service = RagService(
            repository=retrieval.CanonicalAclSearch(
                ranked, authority,
                source=lambda doc_id: {
                    "low": source_document("low", "Hors seuil"),
                    "allowed": source_document("allowed", "Source valide"),
                }.get(doc_id),
            ),
            generator=lambda question, evidence: "Valide [S1]",
            top_k=1,
        )
        response = service.answer("Question ?", context=context)
        self.assertEqual([call[2] for call in ranked.calls], [1, 2])
        self.assertFalse(response.abstained)
        self.assertEqual([citation.document_id for citation in response.citations], ["allowed"])

    def test_only_stale_candidate_is_not_reported_as_honest_abstention(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        authority = CanonicalAclAuthority({
            "stale": AclPolicy("alpha", "private", "alice", (), (), 1, 2),
        })
        service = RagService(
            repository=retrieval.CanonicalAclSearch(FakeRankedSearch([
                candidate("stale", "Ancien contenu", score=0.95)
            ]), authority),
            generator=lambda question, evidence: "Ne doit pas etre appele [S1]",
        )
        with self.assertRaisesRegex(PermissionError, "stale ACL"):
            service.answer("Contenu ?", context=context)

    def test_stale_candidate_plus_below_threshold_candidate_is_acl_error(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        authority = CanonicalAclAuthority({
            "stale": AclPolicy("alpha", "private", "alice", (), (), 1, 2),
            "low": AclPolicy("alpha", "private", "alice", (), (), 1, 1),
        })
        service = RagService(
            repository=retrieval.CanonicalAclSearch(FakeRankedSearch([
                candidate("stale", "Ancien contenu", score=0.9),
                candidate("low", "Hors seuil", score=0.05),
            ]), authority, source=lambda doc_id: {"low": source_document(
                "low", "Hors seuil"
            )}.get(doc_id)),
            generator=lambda question, evidence: "Ne doit pas etre appele [S1]",
            top_k=2,
        )
        with self.assertRaisesRegex(PermissionError, "stale ACL"):
            service.answer("Contenu ?", context=context)

    def test_service_and_acl_bridge_must_use_identical_score_threshold(self):
        authority = CanonicalAclAuthority({})
        bridge = retrieval.CanonicalAclSearch(FakeRankedSearch([]), authority)
        with self.assertRaisesRegex(ValueError, "minimum_score"):
            RagService(repository=bridge, minimum_score=0.9)

    def test_bridge_delegates_import_to_ranked_repository(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        doc = Document(
            document_id="new", content="Un document", tenant_id="alpha",
            visibility="private", owner_id="alice", allowed_groups=(),
            allowed_users=(), classification=1, doc_version=1,
            source_uri="file:///docs/new.md",
        )
        class WritableSearch(FakeRankedSearch):
            def replace_document(self, document, chunks):
                self.saved = (document, list(chunks))
                return type("Result", (), {"document_id": document.document_id,
                                           "chunk_count": len(self.saved[1])})()
        ranked = WritableSearch([])
        service = RagService(repository=retrieval.CanonicalAclSearch(ranked,
            CanonicalAclAuthority({})))
        result = service.import_document(doc, context=context)
        self.assertEqual(result.document_id, "new")
        self.assertEqual(result.chunk_count, 1)
        self.assertEqual(ranked.saved[0], doc)

    def test_qdrant_prefilter_then_canonical_recheck_then_grounded_answer(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        authority = CanonicalAclAuthority({
            "stale": AclPolicy("alpha", "private", "alice", (), (), 1, 2),
            "allowed": AclPolicy("alpha", "private", "alice", (), (), 1, 1),
        })
        points = []
        for item in (
            candidate("stale", "Ancien secret", score=0.99),
            candidate("allowed", "Installer Hermes avec pipx", score=0.88),
        ):
            point = chunk_to_point(item.chunk, [1.0])
            point["score"] = item.score
            points.append(point)

        class FakeQdrant:
            def __init__(self):
                self.calls = []

            def query(self, collection, vector, *, query_filter, limit):
                self.calls.append((collection, vector, query_filter, limit))
                # Deliberately return a stale point despite the prefilter.
                return points[:limit]

        qdrant = FakeQdrant()
        repository = QdrantChunkRepository(
            qdrant, collection="chunks", embed=lambda text: [1.0]
        )
        seen = []

        def generate(question, evidence):
            seen.extend(chunk.document_id for chunk in evidence)
            return "Installez avec pipx [S1]."

        service = RagService(
            repository=retrieval.CanonicalAclSearch(
                repository, authority,
                source=lambda doc_id: {"allowed": source_document(
                    "allowed", "Installer Hermes avec pipx"
                )}.get(doc_id),
            ),
            generator=generate,
            top_k=2,
        )
        response = service.answer("Installer Hermes ?", context=context)

        self.assertEqual(qdrant.calls, [
            ("chunks", [1.0], build_qdrant_filter(context), 2),
            ("chunks", [1.0], build_qdrant_filter(context), 4),
        ])
        self.assertEqual(seen, ["allowed"])
        self.assertEqual([citation.document_id for citation in response.citations], ["allowed"])

    def test_cross_tenant_candidate_cannot_be_generated_or_cited(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        authority = CanonicalAclAuthority({
            "foreign": AclPolicy("beta", "private", "bob", (), (), 1, 1),
        })
        foreign = candidate("foreign", "Secret tenant beta", score=0.95)
        foreign = replace(foreign, chunk=replace(
            foreign.chunk, tenant_id="beta", owner_id="bob"
        ))
        called = []
        service = RagService(
            repository=retrieval.CanonicalAclSearch(
                FakeRankedSearch([foreign]), authority
            ),
            generator=lambda question, evidence: called.append(evidence) or "Fuite [S1]",
        )
        response = service.answer("Secret ?", context=context)
        self.assertTrue(response.abstained)
        self.assertEqual(response.citations, ())
        self.assertEqual(called, [])
