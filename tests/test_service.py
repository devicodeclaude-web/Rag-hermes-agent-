from __future__ import annotations

import unittest
from dataclasses import replace

from rag_hermes.acl import AuthorizationContext
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


if __name__ == "__main__":
    unittest.main()
