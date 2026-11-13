from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from rag_hermes.acl import AuthorizationContext
from rag_hermes.ingestion import Document, chunk_document
import rag_hermes.qdrant_repository as repository_module
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_rest import QdrantRestClient

INDEX_SPEC = Path("qdrant/payload-indexes.json")


def _fixed_vector(_text: str) -> list[float]:
    # Identical vector for every chunk: proves the ACL prefilter, not ranking.
    return [1.0, 0.0, 0.0, 0.0]


@unittest.skipUnless(
    os.environ.get("QDRANT_INTEGRATION_URL"), "Qdrant integration disabled"
)
class QdrantRepositoryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = QdrantRestClient(os.environ["QDRANT_INTEGRATION_URL"])
        self.collection = "hermes_repo_" + uuid.uuid4().hex[:12]
        self.client.create_collection(self.collection, vector_size=4)
        specification = json.loads(INDEX_SPEC.read_text())
        for index in specification["payload_indexes"]:
            self.client.create_payload_index(
                self.collection, index["field_name"], index["field_schema"]
            )
        self.repository = QdrantChunkRepository(
            self.client, collection=self.collection, embed=_fixed_vector
        )

    def tearDown(self) -> None:
        self.client.delete_collection(self.collection)

    def _document(self, doc_id: str, tenant: str, owner: str, text: str) -> Document:
        return Document(
            document_id=doc_id,
            content=text,
            tenant_id=tenant,
            visibility="private",
            owner_id=owner,
            allowed_groups=("support",),
            allowed_users=(),
            classification=1,
            doc_version=1,
            source_uri=f"local://{doc_id}",
        )

    def test_search_never_returns_foreign_tenant_even_with_identical_vector(self) -> None:
        alpha = self._document("alpha-doc", "alpha", "alice", "Installer Hermes localement.")
        beta = self._document("beta-doc", "beta", "bob", "Installer Hermes localement.")
        self.repository.replace_document(alpha, chunk_document(alpha))
        self.repository.replace_document(beta, chunk_document(beta))

        context = AuthorizationContext("alpha", "alice", ("support",), 1)
        results = self.repository.search("Installer Hermes", context=context, limit=10)

        tenants = {result.chunk.tenant_id for result in results}
        self.assertTrue(results)
        self.assertEqual(tenants, {"alpha"})

    def test_replace_document_removes_previous_revision_points(self) -> None:
        first = self._document("guide", "alpha", "alice", "Ancienne version du guide.")
        self.repository.replace_document(first, chunk_document(first))

        second = self._document("guide", "alpha", "alice", "Nouvelle version du guide.")
        self.repository.replace_document(second, chunk_document(second))

        context = AuthorizationContext("alpha", "alice", ("support",), 1)
        results = self.repository.search("version du guide", context=context, limit=10)
        texts = {result.chunk.text for result in results}
        self.assertIn("Nouvelle version du guide.", texts)
        self.assertNotIn("Ancienne version du guide.", texts)

    def test_filtered_scroll_pages_round_trip_with_real_qdrant(self) -> None:
        for index in range(3):
            self.client.upsert(self.collection, [{
                "id": str(uuid.uuid4()),
                "vector": {"dense": _fixed_vector("")},
                "payload": {
                    "tenant_id": "scroll-tenant", "document_id": "scroll-doc",
                    "owner_id": "alice", "sequence": index,
                },
            }])
        query_filter = {"must": [
            {"key": "tenant_id", "match": {"value": "scroll-tenant"}},
            {"key": "document_id", "match": {"value": "scroll-doc"}},
        ]}
        seen = set()
        offset = None
        for _ in range(4):
            points, next_offset = self.client.scroll_filtered_page(
                self.collection, query_filter=query_filter, limit=1, offset=offset
            )
            seen.update(point["id"] for point in points)
            if next_offset is None:
                break
            self.assertNotEqual(next_offset, offset)
            offset = next_offset
        else:
            self.fail("scroll never reached terminal cursor")
        self.assertEqual(len(seen), 3)

    def test_replace_across_real_pages_preserves_foreign_tenant(self) -> None:
        for index in range(2):
            self.client.upsert(self.collection, [{
                "id": str(uuid.UUID(int=index + 11)),
                "vector": {"dense": _fixed_vector("")},
                "payload": {
                    "tenant_id": "alpha", "document_id": "guide",
                    "owner_id": "alice",
                },
            }])
        foreign = self._document("guide", "beta", "bob", "Données du tenant beta.")
        self.repository.replace_document(foreign, chunk_document(foreign))
        with patch.object(repository_module, "_OWNER_SCAN_PAGE_SIZE", 1):
            replacement = self._document("guide", "alpha", "alice", "Version finale du guide.")
            self.repository.replace_document(replacement, chunk_document(replacement))
        alpha = self.repository.search(
            "guide", context=AuthorizationContext("alpha", "alice", (), 1)
        )
        beta = self.repository.search(
            "beta", context=AuthorizationContext("beta", "bob", (), 1)
        )
        self.assertEqual({result.chunk.text for result in alpha}, {"Version finale du guide."})
        self.assertEqual({result.chunk.text for result in beta}, {"Données du tenant beta."})

    def test_replace_refuses_foreign_owner_on_later_real_page(self) -> None:
        for index, owner in enumerate(("alice", "alice", "bob"), start=1):
            self.client.upsert(self.collection, [{
                "id": str(uuid.UUID(int=index)),
                "vector": {"dense": _fixed_vector("")},
                "payload": {
                    "tenant_id": "alpha", "document_id": "guide",
                    "owner_id": owner,
                },
            }])
        attempted = self._document("guide", "alpha", "alice", "Nouvelle version.")
        with patch.object(repository_module, "_OWNER_SCAN_PAGE_SIZE", 2):
            with self.assertRaisesRegex(PermissionError, "owner"):
                self.repository.replace_document(attempted, chunk_document(attempted))
        points = self.client.scroll(self.collection, query_filter={"must": [
            {"key": "tenant_id", "match": {"value": "alpha"}},
            {"key": "document_id", "match": {"value": "guide"}},
        ]}, limit=10)
        self.assertEqual(len(points), 3)
        self.assertEqual([point["payload"]["owner_id"] for point in points],
                         ["alice", "alice", "bob"])

    def test_corrupt_array_owner_is_refused_before_any_mutation(self) -> None:
        self.client.upsert(
            self.collection,
            [
                {
                    "id": str(uuid.uuid4()),
                    "vector": {"dense": _fixed_vector("")},
                    "payload": {
                        "tenant_id": "alpha",
                        "document_id": "guide",
                        "owner_id": ["alice", "bob"],
                    },
                }
            ],
        )
        attempted = self._document(
            "guide", "alpha", "bob", "Tentative de remplacement."
        )

        with self.assertRaisesRegex(PermissionError, "owner"):
            self.repository.replace_document(attempted, chunk_document(attempted))

        points = self.client.scroll(
            self.collection,
            query_filter={
                "must": [
                    {"key": "tenant_id", "match": {"value": "alpha"}},
                    {"key": "document_id", "match": {"value": "guide"}},
                ]
            },
            limit=10,
        )
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["payload"]["owner_id"], ["alice", "bob"])


if __name__ == "__main__":
    unittest.main()
