"""Real Qdrant RBAC checks against an authenticated 1.19 instance in CI.

These tests assert what the SERVER refuses. Python class separation is not an
authorization boundary, so every claim here is a round trip to Qdrant.
"""
from __future__ import annotations

from functools import partial
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from rag_hermes.collection_generation import observe_collection_generation
from rag_hermes.canonical_reconciliation import audit_canonical_copy_index
from rag_hermes.canonical_registry import CanonicalDocumentRegistry
from rag_hermes.canonical_tombstone import CanonicalTombstoneCoordinator
from rag_hermes.index_integrity import audit_qdrant_index
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_identity import mint_collection_token
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_rest import QdrantAuditClient, QdrantRestClient
from rag_hermes.qdrant_service_clients import QdrantRepositoryClients
from rag_hermes.qdrant_store import chunk_to_point


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

    def test_scoped_writer_observes_only_an_operator_provisioned_physical_generation(self) -> None:
        collection = "hermes_gen_" + uuid.uuid4().hex[:12]
        generation = str(uuid.uuid4())
        self.admin.create_collection(collection, vector_size=4, generation_uuid=generation)
        self.addCleanup(self._drop, collection)
        writer = QdrantRestClient(
            self.admin.base_url,
            api_key=_jwt(os.environ["QDRANT_AUTH_ADMIN_KEY"], collection, "prw"),
        )
        observation = observe_collection_generation(writer, collection)
        self.assertEqual(
            (observation.endpoint, observation.collection, observation.generation),
            (writer.base_url, collection, generation),
        )
        # A real alias resolves with GET /collections/{alias}, but must never
        # be accepted as a physical lock/repair target.
        alias = "hermes_alias_" + uuid.uuid4().hex[:12]
        self.admin._request("POST", "/collections/aliases", {
            "actions": [{"create_alias": {
                "collection_name": collection, "alias_name": alias,
            }}],
        })
        with self.assertRaisesRegex(ValueError, "physical collection"):
            observe_collection_generation(writer, alias)
        # A prw JWT cannot provision or replace the physical generation.
        self.assertDenied(writer.delete_collection, collection)
        self.assertDenied(writer.create_collection,
                          "forbidden_" + uuid.uuid4().hex[:12], vector_size=4)

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

    def test_tombstone_repository_uses_the_scoped_writer_through_the_adapter(self) -> None:
        doc = Document(
            document_id="masked", content="Private passage.", tenant_id="alpha",
            visibility="private", owner_id="alice", allowed_groups=(),
            allowed_users=(), classification=1, doc_version=1,
            source_uri="local://masked",
        )
        other = Document(
            document_id="other", content="Other passage.", tenant_id="beta",
            visibility="private", owner_id="bob", allowed_groups=(),
            allowed_users=(), classification=1, doc_version=1,
            source_uri="local://other",
        )
        points = [chunk_to_point(chunk_document(d)[0], [1.0, 0.0, 0.0, 0.0])
                  for d in (doc, other)]
        self.clients.upsert(self.collection, points)
        with tempfile.TemporaryDirectory() as lock_dir:
            repository = QdrantChunkRepository(
                self.clients, collection=self.collection,
                embed=lambda _: [1.0, 0.0, 0.0, 0.0], lock_dir=lock_dir,
            )
            self.assertEqual(repository.apply_document_tombstone(
                doc, chunker=chunk_document,
            ), 1)
        actual = self.admin.retrieve_points(self.collection, [p["id"] for p in points])
        self.assertEqual(len(actual), 2)
        by_id = {point["id"]: point["payload"] for point in actual}
        self.assertEqual(by_id[points[0]["id"]], {**points[0]["payload"], "tombstone": True})
        self.assertEqual(by_id[points[1]["id"]], points[1]["payload"])
        # The default replacement readback still includes the named dense vector.
        self.assertEqual(
            self.clients.retrieve_points(self.collection, [points[1]["id"]])[0]["vector"],
            points[1]["vector"],
        )
        self.assertDenied(
            self.reader.mark_points_tombstoned, self.collection, [points[1]["id"]],
        )
        self.admin.upsert(self.other, [points[1]])
        self.assertDenied(
            self.writer.mark_points_tombstoned, self.other, [points[1]["id"]],
        )
        self.assertIs(self.admin.retrieve_points(
            self.other, [points[1]["id"]], with_vector=False,
        )[0]["payload"]["tombstone"], False)

    def test_canonical_first_mask_over_scoped_clients_on_real_qdrant(self) -> None:
        masked_doc = Document(
            document_id="coordinated", content="alpha beta", tenant_id="alpha",
            visibility="private", owner_id="alice", allowed_groups=(),
            allowed_users=(), classification=1, doc_version=1,
            source_uri="local://coordinated",
        )
        other_doc = Document(
            document_id="other-coordinated", content="gamma", tenant_id="beta",
            visibility="private", owner_id="bob", allowed_groups=(),
            allowed_users=(), classification=1, doc_version=1,
            source_uri="local://other-coordinated",
        )
        chunker = partial(chunk_document, max_tokens=1, overlap_tokens=0)
        masked_chunks = chunker(masked_doc)
        other_chunks = chunker(other_doc)
        self.assertEqual(len(masked_chunks), 2)
        points = [chunk_to_point(c, [1.0, 0.0, 0.0, 0.0])
                  for c in masked_chunks + other_chunks]
        self.clients.upsert(self.collection, points)
        with tempfile.TemporaryDirectory() as directory:
            registry = CanonicalDocumentRegistry(directory)
            registry.register(masked_doc)
            repository = QdrantChunkRepository(
                self.clients, collection=self.collection,
                embed=lambda _: [1.0, 0.0, 0.0, 0.0], lock_dir=directory,
            )
            coordinator = CanonicalTombstoneCoordinator(
                registry, repository, chunker=chunker,
            )
            self.assertEqual(coordinator.mask_document(
                tenant_id="alpha", document_id="coordinated", owner_id="alice",
            ), 2)
            self.assertIsNone(CanonicalDocumentRegistry(directory).source("coordinated"))
            with self.assertRaisesRegex(ValueError, "already inactive"):
                coordinator.mask_document(
                    tenant_id="alpha", document_id="coordinated", owner_id="alice",
                )
        auditor = QdrantAuditClient(
            self.admin.base_url, api_key=_jwt(
                os.environ["QDRANT_AUTH_ADMIN_KEY"], self.collection, "r",
                ttl_seconds=1800,
            ),
        )
        self.assertEqual(audit_qdrant_index(
            auditor, self.collection, masked_chunks + other_chunks,
            expected_tombstone_ids=frozenset(p["id"] for p in points[:2]),
        ).point_count, 3)

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

    def test_tombstone_audit_uses_collection_scoped_read_only_identity(self) -> None:
        self.admin.delete_points(
            self.collection,
            {"must": [{"key": "tenant_id", "match": {"value": "alpha"}}]},
        )
        documents = [Document(
            document_id=f"rbac-{tenant}", content=f"Text for {tenant}.",
            tenant_id=tenant, visibility="private", owner_id="alice",
            allowed_groups=(), allowed_users=(), classification=1,
            doc_version=1, source_uri=f"local://rbac-{tenant}",
        ) for tenant in ("alpha", "beta")]
        chunks = [chunk_document(doc)[0] for doc in documents]
        points = [chunk_to_point(chunk, [1.0, 0.0, 0.0, 0.0]) for chunk in chunks]
        self.admin.upsert(self.collection, points)
        masked_id = points[0]["id"]
        self.admin.mark_points_tombstoned(self.collection, [masked_id])
        self.assertEqual(audit_qdrant_index(
            self.auditor, self.collection, chunks, page_size=1,
            expected_tombstone_ids=frozenset({masked_id}),
        ).point_count, 2)
        reader = QdrantRestClient(self.admin.base_url, api_key=self.audit_key)
        with self.assertRaisesRegex(RuntimeError, "Qdrant HTTP 40[13]"):
            reader.mark_points_tombstoned(self.collection, [points[1]["id"]])
        other_collection = "hermes_other_" + uuid.uuid4().hex[:12]
        self.admin.create_collection(other_collection, vector_size=4)
        self.addCleanup(self.admin.delete_collection, other_collection)
        with self.assertRaisesRegex(RuntimeError, "Qdrant HTTP 40[13]"):
            self.auditor.scroll_page(other_collection, limit=1)
        self.assertIs(self.admin.retrieve_points(
            self.collection, [points[1]["id"]]
        )[0]["payload"]["tombstone"], False)

    def test_canonical_copy_audit_runs_on_the_read_only_audit_credential(self) -> None:
        """The reconciliation diagnostic must need nothing but `r`, server-side."""
        self.admin.delete_points(
            self.collection,
            {"must": [{"key": "tenant_id", "match": {"value": "alpha"}}]},
        )
        document = Document(
            document_id="audit-rbac", content="Texte canonique de l'audit RBAC.",
            tenant_id="alpha", visibility="private", owner_id="alice",
            allowed_groups=(), allowed_users=("alice",), classification=1,
            doc_version=1, source_uri="local://audit-rbac",
        )
        with tempfile.TemporaryDirectory() as directory:
            registry = CanonicalDocumentRegistry(directory)
            registry.register(document)
            chunks = chunk_document(document)
            self.admin.upsert(
                self.collection,
                [chunk_to_point(chunk, [1.0, 0.0, 0.0, 0.0]) for chunk in chunks],
            )
            pin = hashlib.sha256(Path(registry.anchor_path).read_bytes()).hexdigest()
            report = audit_canonical_copy_index(
                directory, anchor_sha256=pin, client=self.auditor,
                collection=self.collection, chunker=chunk_document, page_size=1,
            )
            self.assertEqual(report.point_count, len(chunks))
            # A point the canonical copy does not describe must be refused, so
            # the passing report above is not simply an empty comparison.
            self.admin.upsert(self.collection, [{
                "id": str(uuid.uuid4()), "vector": {"dense": [1.0, 0.0, 0.0, 0.0]},
                "payload": {"tenant_id": "alpha", "document_id": "intrus"},
            }])
            with self.assertRaisesRegex(ValueError, "unexpected indexed points"):
                audit_canonical_copy_index(
                    directory, anchor_sha256=pin, client=self.auditor,
                    collection=self.collection, chunker=chunk_document, page_size=1,
                )
