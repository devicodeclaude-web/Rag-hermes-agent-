"""Canonical recheck of uncalibrated hybrid candidates (not an answer path)."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_filter import build_qdrant_filter
from rag_hermes.qdrant_filter_eval import payload_matches_filter
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_store import chunk_to_point
from tests.test_qdrant_hybrid_candidates import HybridQueryClient


class PrefilteringHybridClient(HybridQueryClient):
    """Applique vraiment le filtre ACL, comme le fait le serveur Qdrant."""

    def query(self, collection, vector, *, query_filter, limit):
        self.queries.append((collection, vector, query_filter, limit))
        return [
            point for point in self.dense_results
            if payload_matches_filter(point["payload"], query_filter)
        ][:limit]

    def query_sparse(self, collection, lexical_weights, *, context, limit):
        self.sparse_queries.append((collection, lexical_weights, context, limit))
        query_filter = build_qdrant_filter(context)
        return [
            point for point in self.sparse_results
            if payload_matches_filter(point["payload"], query_filter)
        ][:limit]


class CanonicalHybridCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "source.jsonl"
        self.doc = Document(
            document_id="guide", content="Installez Hermes avec pipx.",
            tenant_id="alpha", visibility="private", owner_id="alice",
            allowed_groups=(), allowed_users=(), classification=1,
            doc_version=1, source_uri="file:///guide.md",
        )
        self.context = AuthorizationContext("alpha", "alice", (), 1)
        self.client = HybridQueryClient()
        self.repo = QdrantChunkRepository(
            self.client, collection="chunks", embed=lambda text: [1.0, 0.0],
            embed_hybrid=lambda text: ([1.0, 0.0], {"7": 0.5}),
        )
        self.client.dense_results = [{**chunk_to_point(chunk_document(self.doc)[0], [1.0, 0.0]), "score": 0.9}]

    def snapshot(self, *docs: Document):
        self.path.write_text("".join(
            json.dumps(asdict(doc), ensure_ascii=False) + "\n" for doc in docs
        ), encoding="utf-8")
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        return digest

    def test_directly_forged_snapshot_cannot_bypass_digest_check(self) -> None:
        from rag_hermes.canonical_snapshot import PinnedDocumentSnapshot
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        forged = PinnedDocumentSnapshot({"guide": self.doc}, "bogus")
        with self.assertRaisesRegex(ValueError, "canonical source path"):
            CanonicalHybridCandidates(self.repo, forged, expected_sha256="0" * 64)

    def test_wrong_expected_digest_rejects_before_query(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        self.snapshot(self.doc)
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            CanonicalHybridCandidates(self.repo, self.path, expected_sha256="0" * 64)
        self.assertEqual(self.client.queries, [])
        self.assertEqual(self.client.sparse_queries, [])

    def test_server_side_prefilter_hides_the_restrictive_divergence(self) -> None:
        """Limite DÉCLARÉE : avec un vrai préfiltre serveur, ce cas reste muet.

        Le préfiltre Qdrant retire le point avant toute réponse, donc
        `include_denied` ne peut PAS matérialiser le candidat et la divergence
        « index plus restrictif que le canonique » sort en fenêtre vide. Ce test
        fige cette réalité pour que la doc ne promette pas l'inverse.
        """
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        client = PrefilteringHybridClient()
        repo = QdrantChunkRepository(
            client, collection="chunks", embed=lambda text: [1.0, 0.0],
            embed_hybrid=lambda text: ([1.0, 0.0], {"7": 0.5}),
        )
        indexed = chunk_document(replace(self.doc, owner_id="bob"))[0]
        client.dense_results = [{**chunk_to_point(indexed, [1.0, 0.0]), "score": 0.9}]
        source = CanonicalHybridCandidates(
            repo, self.path, expected_sha256=self.snapshot(self.doc)
        )
        self.assertEqual(source.candidates("question", context=self.context), [])

    def test_prefiltering_client_still_returns_a_valid_candidate(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        client = PrefilteringHybridClient()
        repo = QdrantChunkRepository(
            client, collection="chunks", embed=lambda text: [1.0, 0.0],
            embed_hybrid=lambda text: ([1.0, 0.0], {"7": 0.5}),
        )
        client.dense_results = [
            {**chunk_to_point(chunk_document(self.doc)[0], [1.0, 0.0]), "score": 0.9},
        ]
        source = CanonicalHybridCandidates(
            repo, self.path, expected_sha256=self.snapshot(self.doc)
        )
        found = source.candidates("question", context=self.context)
        self.assertEqual([item.chunk.document_id for item in found], ["guide"])

    def test_each_permissive_acl_field_divergence_is_reported(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        canonical_variants = {
            "tenant_id": replace(self.doc, tenant_id="beta"),
            "visibility": replace(self.doc, visibility="public"),
            "owner_id": replace(self.doc, owner_id="bob"),
            "classification": replace(self.doc, classification=5),
            "allowed_groups": replace(self.doc, allowed_groups=("support",)),
            "allowed_users": replace(self.doc, allowed_users=("carol",)),
        }
        for field, canonical in canonical_variants.items():
            with self.subTest(field=field):
                source = CanonicalHybridCandidates(
                    self.repo, self.path, expected_sha256=self.snapshot(canonical)
                )
                # Message de la garde g1 UNIQUEMENT : « ACL payload conflicts »
                # viendrait de _recheck et rendrait ce test non discriminant.
                with self.assertRaisesRegex(PermissionError, "observed ACL conflicts"):
                    source.candidates("question", context=self.context)

    def test_foreign_hit_absent_from_snapshot_does_not_abort_a_valid_one(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        foreign = replace(self.doc, document_id="beta-doc", tenant_id="beta", owner_id="bob")
        self.client.dense_results.insert(0, {
            **chunk_to_point(chunk_document(foreign)[0], [1.0, 0.0]), "score": 1.0,
        })
        source = CanonicalHybridCandidates(
            self.repo, self.path, expected_sha256=self.snapshot(self.doc)
        )
        found = source.candidates("question", context=self.context)
        self.assertEqual([item.chunk.document_id for item in found], ["guide"])

    def test_limit_truncates_the_returned_candidates(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        extra = [replace(self.doc, document_id=f"doc-{index}", content=f"Passage {index}.")
                 for index in range(4)]
        for index, document in enumerate(extra):
            self.client.dense_results.append({
                **chunk_to_point(chunk_document(document)[0], [1.0, 0.0]),
                "score": 0.5 - index / 100,
            })
        source = CanonicalHybridCandidates(
            self.repo, self.path, expected_sha256=self.snapshot(self.doc, *extra)
        )
        self.assertEqual(len(source.candidates("question", context=self.context, limit=5)), 5)
        self.assertEqual(len(source.candidates("question", context=self.context, limit=2)), 2)

    def test_restrictive_index_divergence_is_error_not_empty_window(self) -> None:
        """Index plus restrictif que le canonique : fausse abstention à fermer."""
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        indexed = chunk_document(replace(self.doc, owner_id="bob"))[0]
        self.client.dense_results = [
            {**chunk_to_point(indexed, [1.0, 0.0]), "score": 0.9},
        ]
        source = CanonicalHybridCandidates(
            self.repo, self.path, expected_sha256=self.snapshot(self.doc)
        )
        with self.assertRaisesRegex(PermissionError, "ACL.*conflicts"):
            source.candidates("question", context=self.context)

    def test_foreign_tenant_hit_is_not_reported_as_divergence(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        foreign = replace(self.doc, document_id="beta-doc", tenant_id="beta", owner_id="bob")
        self.client.dense_results = [
            {**chunk_to_point(chunk_document(foreign)[0], [1.0, 0.0]), "score": 0.9},
        ]
        source = CanonicalHybridCandidates(
            self.repo, self.path, expected_sha256=self.snapshot(self.doc, foreign)
        )
        self.assertEqual(source.candidates("question", context=self.context), [])

    def test_uncalibrated_low_rrf_score_is_still_a_candidate(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        source = CanonicalHybridCandidates(
            self.repo, self.path, expected_sha256=self.snapshot(self.doc)
        )
        found = source.candidates("question", context=self.context)
        self.assertEqual([item.chunk.document_id for item in found], ["guide"])
        self.assertLess(found[0].rrf_score, 0.2)

    def test_limit_outside_the_documented_range_is_refused(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        source = CanonicalHybridCandidates(
            self.repo, self.path, expected_sha256=self.snapshot(self.doc)
        )
        for limit in (0, -1, 81, 128, True, 20.0):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "limit"):
                source.candidates("question", context=self.context, limit=limit)

    def test_revoked_owner_is_index_divergence_not_empty_result(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        for version in (1, 2):
            with self.subTest(version=version):
                canonical = replace(self.doc, owner_id="bob", acl_version=version)
                source = CanonicalHybridCandidates(self.repo, self.path, expected_sha256=self.snapshot(canonical))
                with self.assertRaisesRegex(PermissionError, "ACL.*conflicts"):
                    source.candidates("question", context=self.context)

    def test_unknown_authorized_document_is_not_an_empty_answer(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        source = CanonicalHybridCandidates(
            self.repo, self.path, expected_sha256=self.snapshot(replace(self.doc, document_id="other"))
        )
        with self.assertRaisesRegex(PermissionError, "missing canonical document"):
            source.candidates("comment installer ?", context=self.context)

    def test_changed_canonical_text_refuses_index_passage(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        source = CanonicalHybridCandidates(
            self.repo, self.path, expected_sha256=self.snapshot(replace(self.doc, content="Une autre source canonique."))
        )
        with self.assertRaisesRegex(PermissionError, "provenance"):
            source.candidates("question", context=self.context)

    def test_stale_acl_only_is_error_not_empty_result(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        source = CanonicalHybridCandidates(
            self.repo, self.path, expected_sha256=self.snapshot(replace(self.doc, acl_version=2))
        )
        with self.assertRaisesRegex(PermissionError, "stale ACL"):
            source.candidates("question", context=self.context)

    def test_stale_candidate_does_not_hide_valid_candidate(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        valid = replace(self.doc, document_id="valid", content="Source autorisée.")
        source = CanonicalHybridCandidates(
            self.repo, self.path, expected_sha256=self.snapshot(replace(self.doc, acl_version=2), valid)
        )
        self.client.dense_results.append({
            **chunk_to_point(chunk_document(valid)[0], [1.0, 0.0]), "score": 0.8,
        })
        found = source.candidates("question", context=self.context, limit=1)
        self.assertEqual([item.chunk.document_id for item in found], ["valid"])

    def test_empty_window_does_not_claim_honest_abstention(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        self.client.dense_results = []
        source = CanonicalHybridCandidates(self.repo, self.path, expected_sha256=self.snapshot(self.doc))
        self.assertEqual(source.candidates("question", context=self.context), [])

    def test_valid_candidate_is_rechecked_against_independent_source(self) -> None:
        from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
        source = CanonicalHybridCandidates(self.repo, self.path, expected_sha256=self.snapshot(self.doc))
        found = source.candidates("comment installer ?", context=self.context)
        self.assertEqual([item.chunk.document_id for item in found], ["guide"])
        self.assertEqual([item.authorized_by_index for item in found], [True])
        self.assertEqual(found[0].chunk.text, self.doc.content)
        self.assertGreater(found[0].rrf_score, 0)


if __name__ == "__main__":
    unittest.main()
