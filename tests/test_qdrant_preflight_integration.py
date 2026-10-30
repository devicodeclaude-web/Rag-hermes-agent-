from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
import uuid

from rag_hermes.qdrant_preflight import QdrantPreflightError, verify_collection_ready
from rag_hermes.qdrant_rest import QdrantRestClient


INDEX_SPEC = Path("qdrant/payload-indexes.json")


@unittest.skipUnless(
    os.environ.get("QDRANT_INTEGRATION_URL"), "Qdrant integration disabled"
)
class QdrantPreflightIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = QdrantRestClient(os.environ["QDRANT_INTEGRATION_URL"])
        self.collections: list[str] = []
        self.specification = json.loads(INDEX_SPEC.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        for collection in self.collections:
            self.client.delete_collection(collection)

    def _new_collection(self) -> str:
        collection = "hermes_preflight_" + uuid.uuid4().hex[:12]
        self.client.create_collection(collection, vector_size=4)
        self.collections.append(collection)
        return collection

    def test_real_qdrant_accepts_complete_schema_with_tenant_index(self) -> None:
        collection = self._new_collection()
        for index in self.specification["payload_indexes"]:
            self.client.create_payload_index(
                collection, index["field_name"], index["field_schema"]
            )

        report = verify_collection_ready(self.client, collection)

        self.assertEqual(report["collection"], collection)
        self.assertEqual(report["vector_name"], "dense")
        self.assertEqual(report["vector_size"], 4)
        self.assertTrue(report["tenant_index"])

    def test_real_qdrant_refuses_keyword_tenant_id_without_is_tenant(self) -> None:
        collection = self._new_collection()
        for index in self.specification["payload_indexes"]:
            field_schema = index["field_schema"]
            if index["field_name"] == "tenant_id":
                field_schema = "keyword"
            self.client.create_payload_index(
                collection, index["field_name"], field_schema
            )

        with self.assertRaisesRegex(QdrantPreflightError, "is_tenant"):
            verify_collection_ready(self.client, collection)


if __name__ == "__main__":
    unittest.main()
