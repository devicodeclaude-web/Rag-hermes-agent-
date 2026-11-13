from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
import uuid

from rag_hermes.qdrant_preflight import QdrantPreflightError, verify_collection_ready
from rag_hermes.qdrant_provision import QdrantProvisionError, provision_collection
from rag_hermes.qdrant_rest import QdrantRestClient
from rag_hermes.acl import AuthorizationContext, Chunk
from rag_hermes.qdrant_store import chunk_to_point


INDEX_SPEC = Path("qdrant/payload-indexes.json")


@unittest.skipUnless(
    os.environ.get("QDRANT_INTEGRATION_URL"), "Qdrant integration disabled"
)
class QdrantProvisionIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = QdrantRestClient(os.environ["QDRANT_INTEGRATION_URL"])
        self.collections: list[str] = []
        self.specification = json.loads(INDEX_SPEC.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        for collection in self.collections:
            if self.client.collection_exists(collection):
                self.client.delete_collection(collection)

    def _collection(self) -> str:
        collection = "hermes_provision_" + uuid.uuid4().hex[:12]
        self.collections.append(collection)
        return collection

    def test_real_provisioning_is_idempotent(self) -> None:
        collection = self._collection()

        first = provision_collection(
            self.client,
            collection=collection,
            vector_size=4,
            specification=self.specification,
        )
        second = provision_collection(
            self.client,
            collection=collection,
            vector_size=4,
            specification=self.specification,
        )

        self.assertTrue(first["collection_created"])
        self.assertEqual(len(first["indexes_created"]), 11)
        self.assertFalse(second["collection_created"])
        self.assertEqual(second["indexes_created"], [])
        metadata = self.client.get_collection(collection)
        self.assertEqual(len(metadata["payload_schema"]), 11)
        self.assertIs(
            metadata["payload_schema"]["tenant_id"]["params"]["is_tenant"],
            True,
        )

    def test_real_hybrid_collection_stores_and_queries_sparse_vector(self) -> None:
        collection = self._collection()
        report = provision_collection(
            self.client, collection=collection, vector_size=4,
            specification=self.specification, sparse=True,
        )
        self.assertTrue(report["ready"])
        self.assertIsInstance(
            self.client.get_collection(collection)["config"]["params"]["sparse_vectors"]["sparse"],
            dict,
        )
        chunk = Chunk("alpha", "alpha-doc", "Test sparse", "alpha", "private",
                      ("admins",), (), "alice", 2, 1, "b" * 64)
        point = chunk_to_point(chunk, [1.0, 0.0, 0.0, 0.0], sparse_weights={"12": 0.5})
        self.client.upsert(collection, [point])
        alpha = AuthorizationContext("alpha", "alice", ("admins",), 2)
        result = self.client.query_sparse(collection, {"12": 0.5}, context=alpha)
        self.assertEqual([candidate["id"] for candidate in result], [point["id"]])
        beta = AuthorizationContext("beta", "bob", ("admins",), 2)
        self.assertEqual(self.client.query_sparse(collection, {"12": 0.5}, context=beta), [])

    def test_real_explicit_none_modifier_is_accepted(self) -> None:
        collection = self._collection()
        self.client._request("PUT", f"/collections/{collection}", {
            "vectors": {"dense": {"size": 4, "distance": "Cosine"}},
            "sparse_vectors": {"sparse": {"modifier": "none"}},
        })
        report = provision_collection(self.client, collection=collection, vector_size=4,
                                      specification=self.specification, sparse=True)
        self.assertFalse(report["collection_created"])
        self.assertTrue(report["ready"])

    def test_real_sparse_uint8_refused_before_creating_payload_indexes(self) -> None:
        collection = self._collection()
        self.client._request("PUT", f"/collections/{collection}", {
            "vectors": {"dense": {"size": 4, "distance": "Cosine"}},
            "sparse_vectors": {"sparse": {"index": {"datatype": "uint8"}}},
        })
        with self.assertRaisesRegex(QdrantProvisionError, "datatype"):
            provision_collection(self.client, collection=collection, vector_size=4,
                                 specification=self.specification, sparse=True)
        self.assertEqual(self.client.get_collection(collection)["payload_schema"], {})

    def test_real_dense_only_refused_before_creating_payload_indexes(self) -> None:
        collection = self._collection()
        self.client.create_collection(collection, vector_size=4)
        with self.assertRaisesRegex(QdrantProvisionError, "sparse"):
            provision_collection(self.client, collection=collection, vector_size=4,
                                 specification=self.specification, sparse=True)
        self.assertEqual(self.client.get_collection(collection)["payload_schema"], {})

    def test_real_incompatible_collection_is_not_mutated(self) -> None:
        collection = self._collection()
        self.client.create_collection(collection, vector_size=4, distance="Dot")

        with self.assertRaisesRegex(QdrantProvisionError, "Cosine"):
            provision_collection(
                self.client,
                collection=collection,
                vector_size=4,
                specification=self.specification,
            )

        metadata = self.client.get_collection(collection)
        self.assertEqual(metadata["payload_schema"], {})

    def test_real_non_tenant_index_marked_tenant_is_refused_without_mutation(self) -> None:
        collection = self._collection()
        self.client.create_collection(collection, vector_size=4)
        self.client.create_payload_index(
            collection,
            "tenant_id",
            {"type": "keyword", "is_tenant": True},
        )
        self.client.create_payload_index(
            collection,
            "visibility",
            {"type": "keyword", "is_tenant": True},
        )

        with self.assertRaisesRegex(QdrantPreflightError, "visibility"):
            verify_collection_ready(self.client, collection)
        with self.assertRaisesRegex(QdrantProvisionError, "visibility"):
            provision_collection(
                self.client,
                collection=collection,
                vector_size=4,
                specification=self.specification,
            )

        metadata = self.client.get_collection(collection)
        self.assertEqual(set(metadata["payload_schema"]), {"tenant_id", "visibility"})


if __name__ == "__main__":
    unittest.main()
