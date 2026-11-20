"""The V1 service must work end to end with ONLY query+write identities.

Exercised against a real Qdrant with authentication and JWT RBAC enabled: the
admin key provisions, then the service holds two collection-scoped JWTs (`r`
for retrieval, `prw` for point replacement) and never an admin credential.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from rag_hermes.app_factory import build_service
from rag_hermes.canonical_registry import CanonicalWriteThrough
from rag_hermes.http_api import make_app
from rag_hermes.qdrant_provision import provision_collection
from rag_hermes.qdrant_rest import QdrantRestClient
from rag_hermes.retrieval import CanonicalAclSearch
from tests.test_http_api import ALPHA_ALICE_TOKEN, SHARED_AUTHENTICATOR, request
from tests.test_qdrant_auth_integration import _jwt

INDEX_SPEC = Path("qdrant/payload-indexes.json")


def _fixed_vector(_text: str) -> list[float]:
    return [1.0, 0.0, 0.0, 0.0]


class _FixtureTokenizer:
    """Fake CPU tokenizer, not evidence of the BGE tokenizer checkpoint."""

    def __call__(self, text, **_kwargs):
        import re
        matches = list(re.finditer(r"\S+", text))
        return {"input_ids": list(range(len(matches))),
                "offset_mapping": [(m.start(), m.end()) for m in matches]}


@unittest.skipUnless(
    os.environ.get("QDRANT_AUTH_INTEGRATION_URL") and os.environ.get("QDRANT_AUTH_ADMIN_KEY"),
    "authenticated Qdrant integration disabled",
)
class QdrantLeastPrivilegeIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        url = os.environ["QDRANT_AUTH_INTEGRATION_URL"]
        secret = os.environ["QDRANT_AUTH_ADMIN_KEY"]
        self.collection = "hermes_least_priv_" + uuid.uuid4().hex[:12]
        admin = QdrantRestClient(url, api_key=secret)
        provision_collection(
            admin, collection=self.collection, vector_size=4,
            specification=json.loads(INDEX_SPEC.read_text(encoding="utf-8")),
        )
        self.addCleanup(admin.delete_collection, self.collection)
        store = tempfile.TemporaryDirectory()
        self.addCleanup(store.cleanup)
        token_fixture = Path(store.name) / "tokenizer.json"
        token_fixture.write_bytes(b"integration-fixture-only")
        lock_fixture = Path(store.name) / "reranker.lock.json"
        lock_fixture.write_text(json.dumps({
            "repo_id": "test/tokenizer", "revision": "a" * 40,
            "files": [{"path": "tokenizer.json",
                       "sha256": hashlib.sha256(token_fixture.read_bytes()).hexdigest()}],
        }), encoding="utf-8")
        self.env = {
            "RAG_QDRANT_URL": url,
            "RAG_QDRANT_COLLECTION": self.collection,
            "RAG_CANONICAL_STORE": store.name,
            "RAG_TOKENIZER_FILE": str(token_fixture),
            "RAG_TOKENIZER_LOCK": str(lock_fixture),
            "RAG_QDRANT_QUERY_API_KEY": _jwt(secret, self.collection, "r"),
            "RAG_QDRANT_WRITE_API_KEY": _jwt(secret, self.collection, "prw"),
        }

    def _new_app(self):
        return make_app(
            build_service(env=self.env, embed=_fixed_vector, tokenizer=_FixtureTokenizer()),
            authenticator=SHARED_AUTHENTICATOR,
        )

    def _service_clients(self):
        """Unwrap the two Qdrant clients the factory actually wired."""
        service = build_service(
            env=self.env, embed=_fixed_vector, tokenizer=_FixtureTokenizer()
        )
        barrier = service._repository
        assert isinstance(barrier, CanonicalAclSearch)
        write_through = barrier._ranked_search
        assert isinstance(write_through, CanonicalWriteThrough)
        return write_through._repository._client

    def _import(self, app, *, doc_version: int, content: str):
        return request(app, "POST", "/api/documents", {"document": {
            "document_id": "least-privilege", "content": content,
            "visibility": "private", "allowed_groups": ["support"],
            "allowed_users": [], "classification": 1, "doc_version": doc_version,
            "source_uri": "file:///docs/least-privilege.md",
        }}, token=ALPHA_ALICE_TOKEN)

    def test_import_replace_and_cite_without_admin_credentials(self) -> None:
        app = self._new_app()
        status, _, _ = self._import(
            app, doc_version=1, content="Pour installer Hermes, utilisez pipx install hermes-agent.",
        )
        self.assertEqual(status, "201 Created")

        # Replacement drives the write identity through metadata read, owner
        # scroll, upsert, readback and delete — all with the `prw` JWT only.
        replaced_status, _, replaced = self._import(
            app, doc_version=2, content="Pour installer Hermes, utilisez pipx install hermes-agent==2.",
        )
        self.assertEqual(replaced_status, "201 Created")
        self.assertEqual(replaced["document_id"], "least-privilege")

        answer_status, _, answered = request(
            self._new_app(), "POST", "/api/questions",
            {"question": "Comment installer Hermes ?"}, token=ALPHA_ALICE_TOKEN,
        )
        self.assertEqual(answer_status, "200 OK")
        self.assertFalse(answered["abstained"])
        self.assertEqual(answered["citations"][0]["document_id"], "least-privilege")

    def test_service_refuses_to_start_with_an_admin_credential(self) -> None:
        env = dict(self.env)
        env["RAG_QDRANT_API_KEY"] = os.environ["QDRANT_AUTH_ADMIN_KEY"]
        with self.assertRaisesRegex(ValueError, "RAG_QDRANT") as caught:
            build_service(env=env, embed=_fixed_vector, tokenizer=_FixtureTokenizer())
        self.assertNotIn(os.environ["QDRANT_AUTH_ADMIN_KEY"], str(caught.exception))

    def test_service_refuses_an_admin_key_as_either_identity(self) -> None:
        admin = os.environ["QDRANT_AUTH_ADMIN_KEY"]
        for variable in ("RAG_QDRANT_QUERY_API_KEY", "RAG_QDRANT_WRITE_API_KEY"):
            env = dict(self.env)
            env[variable] = admin
            with self.subTest(variable=variable):
                with self.assertRaises(ValueError) as caught:
                    build_service(
                        env=env, embed=_fixed_vector, tokenizer=_FixtureTokenizer()
                    )
                self.assertIn(variable, str(caught.exception))
                self.assertNotIn(admin, str(caught.exception))

    def test_the_wired_identities_are_refused_by_qdrant_beyond_their_scope(self) -> None:
        clients = self._service_clients()
        point = [{"id": str(uuid.uuid4()), "vector": {"dense": _fixed_vector("")},
                  "payload": {"tenant_id": "alpha"}}]
        with self.assertRaisesRegex(RuntimeError, "Qdrant HTTP 40[13]"):
            clients._read.upsert(self.collection, point)
        with self.assertRaisesRegex(RuntimeError, "Qdrant HTTP 40[13]"):
            clients._read.delete_points(
                self.collection, {"must": [{"key": "tenant_id", "match": {"value": "alpha"}}]}
            )
        with self.assertRaisesRegex(RuntimeError, "Qdrant HTTP 40[13]"):
            clients._write.create_payload_index(self.collection, "tenant_id", "keyword")
        with self.assertRaisesRegex(RuntimeError, "Qdrant HTTP 40[13]"):
            clients._write.delete_collection(self.collection)
        # The service still works after those refusals.
        self.assertIsInstance(clients.get_collection(self.collection), dict)
