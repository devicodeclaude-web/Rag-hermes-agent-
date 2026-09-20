import json
import os
import unittest
import uuid
from pathlib import Path

from rag_hermes.acl import AuthorizationContext, Chunk
from rag_hermes.qdrant_filter import build_qdrant_filter
from rag_hermes.qdrant_rest import QdrantRestClient
from rag_hermes.qdrant_store import chunk_to_point


@unittest.skipUnless(os.environ.get("QDRANT_INTEGRATION_URL"), "Qdrant integration disabled")
class QdrantIntegrationTests(unittest.TestCase):
    def test_real_server_enforces_tenant_clearance_and_global_public(self):
        client = QdrantRestClient(os.environ["QDRANT_INTEGRATION_URL"])
        collection = "hermes_acl_test_" + uuid.uuid4().hex[:12]
        same_vector = [1.0, 0.0, 0.0, 0.0]
        chunks = [
            Chunk("global", "global-doc", "Hermes public", "public", "public", (), (), "nous", 0, 1, "a" * 64),
            Chunk("alpha", "alpha-doc", "Alpha secret", "alpha", "private", ("admins",), (), "alice", 2, 1, "b" * 64),
            Chunk("beta", "beta-doc", "Beta secret", "beta", "private", ("admins",), (), "bob", 2, 1, "c" * 64),
        ]

        try:
            client.create_collection(collection, vector_size=4)
            specification = json.loads(Path("qdrant/payload-indexes.json").read_text())
            for index in specification["payload_indexes"]:
                client.create_payload_index(
                    collection, index["field_name"], index["field_schema"]
                )
            client.upsert(
                collection,
                [chunk_to_point(chunk, same_vector) for chunk in chunks],
            )

            alpha = AuthorizationContext("alpha", "alice", ("admins",), 2)
            alpha_points = client.query(
                collection,
                same_vector,
                query_filter=build_qdrant_filter(alpha),
                limit=10,
            )
            alpha_tenants = {point["payload"]["tenant_id"] for point in alpha_points}
            self.assertEqual(alpha_tenants, {"alpha", "public"})

            low_clearance = AuthorizationContext("alpha", "alice", ("admins",), 0)
            low_points = client.query(
                collection,
                same_vector,
                query_filter=build_qdrant_filter(low_clearance),
                limit=10,
            )
            low_tenants = {point["payload"]["tenant_id"] for point in low_points}
            self.assertEqual(low_tenants, {"public"})

            beta = AuthorizationContext("beta", "bob", ("admins",), 2)
            beta_points = client.query(
                collection,
                same_vector,
                query_filter=build_qdrant_filter(beta),
                limit=10,
            )
            beta_tenants = {point["payload"]["tenant_id"] for point in beta_points}
            self.assertEqual(beta_tenants, {"beta", "public"})
        finally:
            client.delete_collection(collection)


if __name__ == "__main__":
    unittest.main()
