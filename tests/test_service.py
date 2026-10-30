from __future__ import annotations

import unittest
from dataclasses import replace

from rag_hermes.acl import AuthorizationContext
from rag_hermes.generator import GenerationError
from rag_hermes.ingestion import Document
from rag_hermes.service import RagService


class RagServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = AuthorizationContext(
            tenant_id="alpha",
            user_id="alice",
            groups=("support",),
            clearance=1,
        )
        self.document = Document(
            document_id="guide-installation",
            content="Pour installer Hermes, utilisez la commande pipx install hermes-agent.",
            tenant_id="alpha",
            visibility="private",
            owner_id="alice",
            allowed_groups=("support",),
            allowed_users=(),
            classification=1,
            doc_version=1,
            source_uri="file:///docs/guide-installation.md",
        )

    def test_answer_with_trace_exposes_ranked_evidence_and_cited_chunks(self) -> None:
        def generate(question, evidence):
            return "La première source suffit [S1]."

        service = RagService(generator=generate, top_k=2)
        first = replace(
            self.document,
            document_id="guide-installation",
            content="Installer Hermes avec pipx install hermes-agent.",
            source_uri="file:///docs/install.md",
        )
        second = replace(
            self.document,
            document_id="guide-configuration",
            content="Configurer Hermes après installation avec hermes config set.",
            source_uri="file:///docs/config.md",
        )
        service.import_document(first, context=self.context)
        service.import_document(second, context=self.context)

        trace = service.answer_with_trace(
            "Comment installer et configurer Hermes ?",
            context=self.context,
        )

        self.assertFalse(trace.response.abstained)
        self.assertEqual(len(trace.retrieved_chunks), 2)
        self.assertEqual(
            trace.cited_chunks,
            (trace.retrieved_chunks[0],),
        )
        self.assertEqual(
            trace.response.citations[0].chunk_id,
            trace.cited_chunks[0].chunk_id,
        )

    def test_import_then_question_returns_grounded_answer_and_citation(self) -> None:
        service = RagService()

        imported = service.import_document(self.document, context=self.context)
        response = service.answer(
            "Comment installer Hermes ?",
            context=self.context,
        )

        self.assertEqual(imported.document_id, "guide-installation")
        self.assertGreater(imported.chunk_count, 0)
        self.assertFalse(response.abstained)
        self.assertIn("pipx install hermes-agent", response.answer)
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0].document_id, "guide-installation")
        self.assertEqual(
            response.citations[0].source_uri,
            "file:///docs/guide-installation.md",
        )

    def test_configured_generator_receives_question_and_authorized_evidence(self) -> None:
        calls = []

        def generate(question, evidence):
            calls.append((question, evidence))
            return "Installez Hermes avec pipx [S1]."

        service = RagService(generator=generate)
        service.import_document(self.document, context=self.context)

        response = service.answer(
            "Comment installer Hermes ?",
            context=self.context,
        )

        self.assertEqual(response.answer, "Installez Hermes avec pipx [S1].")
        self.assertFalse(response.abstained)
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(calls[0][0], "Comment installer Hermes ?")
        self.assertEqual(calls[0][1][0].document_id, "guide-installation")
        self.assertIn("pipx install hermes-agent", calls[0][1][0].text)

    def test_generator_receives_top_k_authorized_evidence(self) -> None:
        calls = []

        def generate(question, evidence):
            calls.append(evidence)
            return "Configurez puis lancez Hermes [S1][S2]."

        service = RagService(generator=generate, top_k=3)
        first = replace(
            self.document,
            document_id="guide-installation",
            content="Pour installer Hermes, utilisez pipx install hermes-agent.",
            source_uri="file:///docs/install.md",
        )
        second = replace(
            self.document,
            document_id="guide-config",
            content="Pour configurer Hermes, editez le fichier hermes config set.",
            source_uri="file:///docs/config.md",
        )
        service.import_document(first, context=self.context)
        service.import_document(second, context=self.context)

        response = service.answer(
            "Comment installer et configurer Hermes ?",
            context=self.context,
        )

        self.assertFalse(response.abstained)
        self.assertGreaterEqual(len(calls[0]), 2)
        cited_documents = {citation.document_id for citation in response.citations}
        self.assertEqual(cited_documents, {"guide-installation", "guide-config"})
        self.assertEqual(len(response.citations), 2)

    def test_repeated_marker_produces_a_single_deduplicated_citation(self) -> None:
        def generate(question, evidence):
            return "Installez [S1] puis relancez [S1] enfin verifiez [S1]."

        service = RagService(generator=generate, top_k=3)
        service.import_document(self.document, context=self.context)

        response = service.answer(
            "Comment installer Hermes ?",
            context=self.context,
        )

        self.assertFalse(response.abstained)
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0].document_id, "guide-installation")

    def test_citations_follow_first_cited_order(self) -> None:
        seen: dict[str, tuple] = {}

        def generate(question, evidence):
            seen["evidence"] = evidence
            # Cite the second retrieved source before the first.
            return "D'abord [S2] puis [S1]."

        service = RagService(generator=generate, top_k=3)
        first = replace(
            self.document,
            document_id="guide-installation",
            content="Pour installer Hermes, utilisez pipx install hermes-agent.",
            source_uri="file:///docs/install.md",
        )
        second = replace(
            self.document,
            document_id="guide-config",
            content="Pour configurer Hermes, editez le fichier hermes config set.",
            source_uri="file:///docs/config.md",
        )
        service.import_document(first, context=self.context)
        service.import_document(second, context=self.context)

        response = service.answer(
            "Comment installer et configurer Hermes ?",
            context=self.context,
        )

        evidence = seen["evidence"]
        self.assertGreaterEqual(len(evidence), 2)
        self.assertEqual(len(response.citations), 2)
        # [S2] was cited first, so evidence[1] leads, then evidence[0].
        self.assertEqual(
            [citation.chunk_id for citation in response.citations],
            [evidence[1].chunk_id, evidence[0].chunk_id],
        )

    def test_only_cited_evidence_is_returned_as_citation(self) -> None:
        def generate(question, evidence):
            return "La reponse vient de la premiere source seulement [S1]."

        service = RagService(generator=generate, top_k=3)
        first = replace(
            self.document,
            document_id="guide-installation",
            content="Pour installer Hermes, utilisez pipx install hermes-agent.",
            source_uri="file:///docs/install.md",
        )
        second = replace(
            self.document,
            document_id="guide-config",
            content="Pour configurer Hermes, editez le fichier hermes config set.",
            source_uri="file:///docs/config.md",
        )
        service.import_document(first, context=self.context)
        service.import_document(second, context=self.context)

        response = service.answer(
            "Comment installer et configurer Hermes ?",
            context=self.context,
        )

        self.assertFalse(response.abstained)
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0].document_id, "guide-installation")

    def test_pathological_marker_from_generator_is_ignored_without_error(self) -> None:
        def generate(question, evidence):
            return "Voir [S1] et un marqueur pathologique [S" + "9" * 10_000 + "]."

        service = RagService(generator=generate, top_k=3)
        service.import_document(self.document, context=self.context)

        response = service.answer(
            "Comment installer Hermes ?",
            context=self.context,
        )

        self.assertFalse(response.abstained)
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0].document_id, "guide-installation")

    def test_non_abstention_answer_without_resolved_citation_fails_closed(self) -> None:
        def generate(question, evidence):
            return "Réponse sans aucune source citée."

        service = RagService(generator=generate, top_k=3)
        service.import_document(self.document, context=self.context)

        with self.assertRaises(GenerationError):
            service.answer("Comment installer Hermes ?", context=self.context)

    def test_only_out_of_range_markers_fail_closed(self) -> None:
        def generate(question, evidence):
            return "Voir la source [S9]."

        service = RagService(generator=generate, top_k=3)
        service.import_document(self.document, context=self.context)

        with self.assertRaises(GenerationError):
            service.answer("Comment installer Hermes ?", context=self.context)

    def test_generator_can_abstain_without_exposing_irrelevant_citations(self) -> None:
        service = RagService(
            generator=lambda question, evidence: (
                "Je ne dispose pas de sources suffisantes pour répondre."
            )
        )
        service.import_document(self.document, context=self.context)

        response = service.answer(
            "Comment installer Hermes ?",
            context=self.context,
        )

        self.assertTrue(response.abstained)
        self.assertEqual(response.citations, ())

    def test_question_without_sufficient_evidence_abstains(self) -> None:
        service = RagService()
        service.import_document(self.document, context=self.context)

        response = service.answer(
            "Quel temps fera-t-il demain ?",
            context=self.context,
        )

        self.assertTrue(response.abstained)
        self.assertEqual(response.citations, ())
        self.assertIn("sources suffisantes", response.answer)

    def test_import_rejects_document_for_another_tenant(self) -> None:
        service = RagService()
        foreign_document = replace(self.document, tenant_id="beta")

        with self.assertRaisesRegex(PermissionError, "tenant"):
            service.import_document(foreign_document, context=self.context)

    def test_import_rejects_document_owned_by_another_user(self) -> None:
        service = RagService()
        foreign_document = replace(self.document, owner_id="bob")

        with self.assertRaisesRegex(PermissionError, "owner"):
            service.import_document(foreign_document, context=self.context)

    def test_existing_document_cannot_be_overwritten_by_another_owner(self) -> None:
        service = RagService()
        service.import_document(self.document, context=self.context)
        bob_context = replace(self.context, user_id="bob")
        replacement = replace(
            self.document,
            owner_id="bob",
            content="Contenu remplacé par Bob.",
        )

        with self.assertRaisesRegex(PermissionError, "existing document owner"):
            service.import_document(replacement, context=bob_context)

    # --- Reranking (top-k retrieval + rescoring) ---

    def _install_two_docs(self, service: RagService) -> None:
        first = replace(
            self.document,
            document_id="guide-installation",
            content="Pour installer Hermes, utilisez pipx install hermes-agent.",
            source_uri="file:///docs/install.md",
        )
        second = replace(
            self.document,
            document_id="guide-config",
            content="Pour installer et configurer Hermes, editez hermes config set.",
            source_uri="file:///docs/config.md",
        )
        service.import_document(first, context=self.context)
        service.import_document(second, context=self.context)

    def test_reranker_reorders_candidates_before_generation(self) -> None:
        seen = {}

        def rerank(question, chunks):
            seen["chunks"] = chunks
            # Score inversely to retrieval order: last retrieved becomes best.
            return [float(index) for index in range(len(chunks))]

        def generate(question, evidence):
            seen["evidence"] = evidence
            return "Réponse fondée [S1]."

        service = RagService(
            generator=generate, reranker=rerank, retrieval_k=5, top_k=1
        )
        self._install_two_docs(service)

        response = service.answer(
            "Comment installer Hermes ?",
            context=self.context,
        )

        self.assertFalse(response.abstained)
        # Reranker saw at least the two retrieved candidates.
        self.assertGreaterEqual(len(seen["chunks"]), 2)
        # top_k=1 after reranking: only the reranker's best chunk is evidence.
        self.assertEqual(len(seen["evidence"]), 1)
        # The reranker's highest score was the LAST retrieved chunk.
        self.assertEqual(seen["evidence"][0].chunk_id, seen["chunks"][-1].chunk_id)
        self.assertEqual(len(response.citations), 1)

    def test_reranker_receives_retrieval_k_candidates_and_narrows_to_top_k(self) -> None:
        seen = {}

        def rerank(question, chunks):
            seen["count"] = len(chunks)
            return [1.0 for _ in chunks]

        def generate(question, evidence):
            seen["evidence_count"] = len(evidence)
            return "Réponse [S1]."

        service = RagService(
            generator=generate, reranker=rerank, retrieval_k=10, top_k=2
        )
        self._install_two_docs(service)

        service.answer("Comment installer Hermes ?", context=self.context)

        # Both installed docs are retrieval candidates; top_k=2 keeps both.
        self.assertEqual(seen["count"], 2)
        self.assertEqual(seen["evidence_count"], 2)

    def test_reranker_score_length_mismatch_fails_closed(self) -> None:
        def rerank(question, chunks):
            return [1.0]  # wrong length when >1 candidate

        def generate(question, evidence):
            return "Réponse [S1]."

        service = RagService(
            generator=generate, reranker=rerank, retrieval_k=10, top_k=2
        )
        self._install_two_docs(service)

        # An injected reranker returning a wrong score count is a failure of a
        # server-side generation component, not a client request error. It must
        # surface as GenerationError (mapped to 5xx), never a bare ValueError
        # that the HTTP layer would report as a 400 Bad Request.
        with self.assertRaises(GenerationError):
            service.answer("Comment installer Hermes ?", context=self.context)

    def test_reranker_non_list_scores_fails_closed(self) -> None:
        def rerank(question, chunks):
            return "not-a-list"  # type: ignore[return-value]  # malformed reranker output

        def generate(question, evidence):
            return "Réponse [S1]."

        service = RagService(
            generator=generate, reranker=rerank, retrieval_k=10, top_k=2
        )
        self._install_two_docs(service)

        with self.assertRaises(GenerationError):
            service.answer("Comment installer Hermes ?", context=self.context)

    def test_retrieval_k_must_be_at_least_top_k(self) -> None:
        with self.assertRaises(ValueError):
            RagService(retrieval_k=2, top_k=5)


if __name__ == "__main__":
    unittest.main()
