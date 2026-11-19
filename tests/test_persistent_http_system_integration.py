from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from rag_hermes.app_factory import build_service
from rag_hermes.canonical_registry import CanonicalDocumentRegistry
from rag_hermes.http_api import make_app
from rag_hermes.qdrant_provision import provision_collection
from rag_hermes.qdrant_rest import QdrantRestClient
from tests.test_http_api import (
    ALPHA_ALICE_TOKEN,
    ALPHA_BOB_TOKEN,
    SHARED_AUTHENTICATOR,
    request,
)


INDEX_SPEC = Path("qdrant/payload-indexes.json")


def _fixed_vector(_text: str) -> list[float]:
    return [1.0, 0.0, 0.0, 0.0]


@unittest.skipUnless(
    os.environ.get("QDRANT_INTEGRATION_URL"), "Qdrant integration disabled"
)
class PersistentHttpSystemIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.url = os.environ["QDRANT_INTEGRATION_URL"]
        self.client = QdrantRestClient(self.url)
        self.collection = "hermes_http_system_" + uuid.uuid4().hex[:12]
        specification = json.loads(INDEX_SPEC.read_text(encoding="utf-8"))
        provision_collection(
            self.client,
            collection=self.collection,
            vector_size=4,
            specification=specification,
        )
        self.env = {
            "RAG_QDRANT_URL": self.url,
            "RAG_QDRANT_COLLECTION": self.collection,
        }
        # SEC-01 : un service adossé à Qdrant exige une autorité ACL canonique
        # locale. Le répertoire survit aux deux démarrages du test, donc le
        # registre est rechargé depuis le disque au « redémarrage ».
        store = tempfile.TemporaryDirectory()
        self.addCleanup(store.cleanup)
        self.store_dir = store.name
        self.env["RAG_CANONICAL_STORE"] = self.store_dir

    def tearDown(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)

    def _new_app(self):
        # Identité dérivée côté serveur du jeton : Alice et Bob (tenant alpha).
        return make_app(
            build_service(env=self.env, embed=_fixed_vector),
            authenticator=SHARED_AUTHENTICATOR,
        )

    def test_import_survives_service_restart_and_returns_citation(self) -> None:
        first_app = self._new_app()
        import_status, _, imported = request(
            first_app,
            "POST",
            "/api/documents",
            {
                "document": {
                    "document_id": "persistent-guide",
                    "content": "Pour installer Hermes, utilisez pipx install hermes-agent.",
                    "visibility": "private",
                    "allowed_groups": ["support"],
                    "allowed_users": [],
                    "classification": 1,
                    "doc_version": 1,
                    "source_uri": "file:///docs/persistent-guide.md",
                },
            },
            token=ALPHA_ALICE_TOKEN,
        )
        self.assertEqual(import_status, "201 Created")
        self.assertEqual(imported["document_id"], "persistent-guide")

        restarted_app = self._new_app()
        answer_status, _, answered = request(
            restarted_app,
            "POST",
            "/api/questions",
            {"question": "Comment installer Hermes ?"},
            token=ALPHA_ALICE_TOKEN,
        )

        self.assertEqual(answer_status, "200 OK")
        self.assertFalse(answered["abstained"])
        self.assertEqual(
            answered["citations"][0]["document_id"], "persistent-guide"
        )
        self.assertEqual(
            answered["citations"][0]["source_uri"],
            "file:///docs/persistent-guide.md",
        )
        # SEC-01 : la réponse n'a pu franchir la barrière que parce que le
        # registre canonique, rechargé du disque au redémarrage, porte la
        # révision du document — l'index n'a pas été sa propre autorité.
        registry = CanonicalDocumentRegistry(self.store_dir)
        stored = registry.source("persistent-guide")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.tenant_id, "alpha")
        self.assertEqual(stored.owner_id, "alice")
        self.assertEqual(stored.allowed_groups, ("support",))

    def test_restart_does_not_allow_another_user_to_hijack_document_owner(self) -> None:
        first_app = self._new_app()
        original_document = {
            "document_id": "owned-guide",
            "content": "Contenu original appartenant à Alice.",
            "visibility": "private",
            "allowed_groups": ["support"],
            "allowed_users": [],
            "classification": 1,
            "doc_version": 1,
            "source_uri": "file:///docs/original.md",
        }
        status, _, _ = request(
            first_app,
            "POST",
            "/api/documents",
            {"document": original_document},
            token=ALPHA_ALICE_TOKEN,
        )
        self.assertEqual(status, "201 Created")

        # Bob (jeton distinct, tenant alpha) ne peut pas reprendre un document
        # dont Alice est propriétaire : l'owner vient du jeton, pas du corps.
        restarted_app = self._new_app()
        hijacked_document = {
            **original_document,
            "content": "Contenu remplacé par Bob.",
            "doc_version": 2,
            "source_uri": "file:///docs/hijacked.md",
        }
        hijack_status, _, hijack_response = request(
            restarted_app,
            "POST",
            "/api/documents",
            {"document": hijacked_document},
            token=ALPHA_BOB_TOKEN,
        )

        self.assertEqual(hijack_status, "403 Forbidden")
        self.assertEqual(hijack_response["error"], "forbidden")

        answer_status, _, answered = request(
            restarted_app,
            "POST",
            "/api/questions",
            {"question": "Contenu original"},
            token=ALPHA_ALICE_TOKEN,
        )
        self.assertEqual(answer_status, "200 OK")
        self.assertEqual(answered["citations"][0]["source_uri"], "file:///docs/original.md")
        self.assertNotIn("Bob", answered["answer"])

    def test_replayed_allowlist_at_same_acl_version_is_refused_before_qdrant_write(self) -> None:
        """Le registre refuse le rejeu ; Bob reste révoqué après redémarrage."""
        app = self._new_app()
        base = {
            "document_id": "revocable-guide",
            "content": "Une instruction secrète pour le propriétaire.",
            "visibility": "private",
            "allowed_groups": [],
            "allowed_users": ["bob"],
            "classification": 1,
            "doc_version": 1,
            "acl_version": 1,
            "source_uri": "file:///docs/revocable-guide.md",
        }
        status, _, _ = request(
            app, "POST", "/api/documents", {"document": base}, token=ALPHA_ALICE_TOKEN
        )
        self.assertEqual(status, "201 Created")
        status, _, _ = request(
            app, "POST", "/api/documents",
            {"document": {**base, "allowed_users": [], "acl_version": 2}},
            token=ALPHA_ALICE_TOKEN,
        )
        self.assertEqual(status, "201 Created")
        registry = CanonicalDocumentRegistry(self.store_dir)
        before = registry.path.read_bytes()

        status, _, body = request(
            app, "POST", "/api/documents",
            {"document": {**base, "acl_version": 2}}, token=ALPHA_ALICE_TOKEN,
        )
        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(body["error"], "invalid_request")
        self.assertEqual(registry.path.read_bytes(), before)

        restarted = self._new_app()
        status, _, answered = request(
            restarted, "POST", "/api/questions",
            {"question": "instruction secrète"}, token=ALPHA_BOB_TOKEN,
        )
        self.assertEqual(status, "200 OK")
        self.assertTrue(answered["abstained"])
        self.assertEqual(answered["citations"], [])


if __name__ == "__main__":
    unittest.main()
