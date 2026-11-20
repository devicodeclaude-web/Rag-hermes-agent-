"""Real Qdrant RBAC checks against an authenticated 1.19 instance in CI.

These tests assert what the SERVER refuses. Python class separation is not an
authorization boundary, so every claim here is a round trip to Qdrant.
"""
from __future__ import annotations

import os
import unittest
import uuid

from rag_hermes.qdrant_identity import mint_collection_token
from rag_hermes.qdrant_rest import QdrantAuditClient, QdrantRestClient
from rag_hermes.qdrant_service_clients import QdrantRepositoryClients


def _jwt(secret: str, collection: str, access: str, *, ttl_seconds: int = 3600) -> str:
    return mint_collection_token(
        secret, collection=collection, access=access, ttl_seconds=ttl_seconds
    )


@unittest.skipUnless(
    os.environ.get("QDRANT_AUTH_INTEGRATION_URL") and os.environ.get("QDRANT_AUTH_ADMIN_KEY"),
    "authenticated Qdrant integration disabled",
)
class QdrantAuthIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        url = os.environ["QDRANT_AUTH_INTEGRATION_URL"]
        secret = os.environ["QDRANT_AUTH_ADMIN_KEY"]
        self.collection = "hermes_rbac_" + uuid.uuid4().hex[:12]
        self.other = "hermes_other_" + uuid.uuid4().hex[:12]
        self.admin = QdrantRestClient(url, api_key=secret)
        self.admin.create_collection(self.collection, vector_size=4)
        self.addCleanup(self._drop, self.collection)
        self.admin.create_collection(self.other, vector_size=4)
        self.addCleanup(self._drop, self.other)
        self.reader = QdrantRestClient(url, api_key=_jwt(secret, self.collection, "r"))
        self.writer = QdrantRestClient(url, api_key=_jwt(secret, self.collection, "prw"))
        self.clients = QdrantRepositoryClients(self.reader, self.writer)
        self.point_id = str(uuid.uuid4())
        self.points = [{
            "id": self.point_id, "vector": {"dense": [1.0, 0.0, 0.0, 0.0]},
            "payload": {"tenant_id": "alpha"},
        }]
        self.filter = {"must": [{"key": "tenant_id", "match": {"value": "alpha"}}]}

    def _drop(self, collection: str) -> None:
        if self.admin.collection_exists(collection):
            self.admin.delete_collection(collection)

    def assertDenied(self, call, *args, **kwargs) -> None:
        with self.assertRaisesRegex(RuntimeError, "Qdrant HTTP 40[13]"):
            call(*args, **kwargs)

    def test_read_identity_cannot_mutate_points(self) -> None:
        self.assertIsInstance(self.reader.get_collection(self.collection), dict)
        self.assertDenied(self.reader.upsert, self.collection, self.points)
        self.assertDenied(self.reader.delete_points, self.collection, self.filter)

    def test_write_identity_cannot_administer_or_destroy_the_collection(self) -> None:
        self.assertDenied(
            self.writer.create_payload_index, self.collection, "tenant_id", "keyword"
        )
        self.assertDenied(self.writer.delete_collection, self.collection)
        self.assertDenied(
            self.writer.create_collection, "forbidden_" + uuid.uuid4().hex[:12], vector_size=4
        )
        self.assertTrue(self.admin.collection_exists(self.collection))

    def test_neither_identity_reaches_another_collection(self) -> None:
        self.assertDenied(self.reader.get_collection, self.other)
        self.assertDenied(self.writer.upsert, self.other, self.points)
        self.assertDenied(self.writer.delete_collection, self.other)
        self.assertTrue(self.admin.collection_exists(self.other))

    def test_replacement_round_trip_uses_only_the_two_identities(self) -> None:
        self.clients.upsert(self.collection, self.points)
        hits = self.clients.query(
            self.collection, [1.0, 0.0, 0.0, 0.0], query_filter=self.filter, limit=2,
        )
        self.assertEqual([point["id"] for point in hits], [self.point_id])
        self.assertEqual(
            self.clients.retrieve_points(self.collection, [self.point_id])[0]["id"],
            self.point_id,
        )
        self.clients.delete_points(self.collection, self.filter)
        self.assertEqual(self.reader.query(
            self.collection, [1.0, 0.0, 0.0, 0.0], query_filter=self.filter,
        ), [])

    def test_missing_or_wrong_credentials_are_rejected(self) -> None:
        for key in ("", "wrong-ci-key"):
            with self.subTest(key_present=bool(key)):
                self.assertDenied(
                    QdrantRestClient(self.admin.base_url, api_key=key).get_collection,
                    self.collection,
                )

    def test_a_read_token_can_still_scroll_the_whole_collection(self) -> None:
        """Documented limit, not a desired behaviour.

        Qdrant scopes a token to a collection, never to the service's tenant
        filter: the query identity could read every tenant of the V1
        collection. Tenant isolation therefore stays an application guarantee
        (the canonical ACL barrier), not a server-side one.
        """
        self.clients.upsert(self.collection, self.points)
        unfiltered = self.reader._request(
            "POST", f"/collections/{self.collection}/points/scroll", {"limit": 10},
        )
        self.assertEqual(
            [point["id"] for point in unfiltered["result"]["points"]], [self.point_id]
        )


@unittest.skipUnless(
    os.environ.get("QDRANT_AUTH_INTEGRATION_URL") and os.environ.get("QDRANT_AUTH_ADMIN_KEY"),
    "authenticated Qdrant integration disabled",
)
class QdrantAuditIdentityIntegrationTests(unittest.TestCase):
    """The audit reader's own credential must be read-only, server-side."""

    def setUp(self) -> None:
        url = os.environ["QDRANT_AUTH_INTEGRATION_URL"]
        secret = os.environ["QDRANT_AUTH_ADMIN_KEY"]
        self.collection = "hermes_audit_" + uuid.uuid4().hex[:12]
        self.admin = QdrantRestClient(url, api_key=secret)
        self.admin.create_collection(self.collection, vector_size=4)
        self.addCleanup(self._drop)
        self.audit_key = _jwt(secret, self.collection, "r", ttl_seconds=1800)
        self.auditor = QdrantAuditClient(url, api_key=self.audit_key)
        self.point_id = str(uuid.uuid4())
        self.admin.upsert(self.collection, [{
            "id": self.point_id, "vector": {"dense": [1.0, 0.0, 0.0, 0.0]},
            "payload": {"tenant_id": "alpha"},
        }])

    def _drop(self) -> None:
        if self.admin.collection_exists(self.collection):
            self.admin.delete_collection(self.collection)

    def test_the_audit_identity_reads_every_point_and_cannot_write(self) -> None:
        points, cursor = self.auditor.scroll_page(self.collection, limit=10)
        self.assertEqual([point["id"] for point in points], [self.point_id])
        self.assertIsNone(cursor)
        # The audit object offers no mutation at all, so the only way to try
        # one with this credential is a raw read/write client — which Qdrant
        # must refuse.
        with_audit_key = QdrantRestClient(self.admin.base_url, api_key=self.audit_key)
        for call, args in (
            (with_audit_key.upsert, (self.collection, [{
                "id": str(uuid.uuid4()), "vector": {"dense": [0.0, 1.0, 0.0, 0.0]},
                "payload": {"tenant_id": "alpha"},
            }])),
            (with_audit_key.delete_points, (
                self.collection,
                {"must": [{"key": "tenant_id", "match": {"value": "alpha"}}]},
            )),
            (with_audit_key.delete_collection, (self.collection,)),
        ):
            with self.subTest(call=call.__name__):
                with self.assertRaisesRegex(RuntimeError, "Qdrant HTTP 40[13]"):
                    call(*args)
        self.assertTrue(self.admin.collection_exists(self.collection))
        self.assertEqual(
            [point["id"] for point in self.admin.scroll(self.collection, query_filter={
                "must": [{"key": "tenant_id", "match": {"value": "alpha"}}]
            }, limit=10)],
            [self.point_id],
        )
