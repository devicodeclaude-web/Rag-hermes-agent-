from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from rag_hermes.acl import AuthorizationContext
from rag_hermes.ingestion import Document, chunk_document
import rag_hermes.qdrant_repository as repository_module
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_rest import QdrantRestClient
from rag_hermes.qdrant_store import chunk_to_point

INDEX_SPEC = Path("qdrant/payload-indexes.json")


def _fixed_vector(_text: str) -> list[float]:
    # Identical vector for every chunk: proves the ACL prefilter, not ranking.
    return [1.0, 0.0, 0.0, 0.0]


def _blocked_replace_worker(url, collection, directory, document, entered, release, results) -> None:
    client = QdrantRestClient(url)
    def embed(text):
        entered.set()
        if not release.wait(15):
            raise TimeoutError("test worker release not received")
        return _fixed_vector(text)

    try:
        repo = QdrantChunkRepository(
            client, collection=collection, embed=embed, lock_dir=directory,
        )
        repo.replace_document(document, chunk_document(document))
        results.put("completed")
    except Exception as exc:
        results.put(type(exc).__name__ + ": " + str(exc))


def _contending_replace_worker(url, collection, directory, document, results) -> None:
    try:
        repo = QdrantChunkRepository(
            QdrantRestClient(url), collection=collection, embed=_fixed_vector,
            lock_dir=directory, lock_timeout=0.2,
        )
        repo.replace_document(document, chunk_document(document))
        results.put("unexpectedly completed")
    except Exception as exc:
        results.put(type(exc).__name__ + ": " + str(exc))


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

    def test_two_processes_serialize_replacement_on_real_qdrant(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        first = self._document("flock", "alpha", "alice", "Révision initiale.")
        held = self._document("flock", "alpha", "alice", "Révision en cours.")
        second = self._document("flock", "alpha", "alice", "Révision suivante.")
        self.repository.replace_document(first, chunk_document(first))
        with tempfile.TemporaryDirectory() as directory:
            entered, release = ctx.Event(), ctx.Event()
            results = ctx.Queue()
            url = os.environ["QDRANT_INTEGRATION_URL"]
            worker = ctx.Process(
                target=_blocked_replace_worker,
                args=(url, self.collection, directory, held, entered, release, results),
            )
            contender = ctx.Process(
                target=_contending_replace_worker,
                args=(url, self.collection, directory, second, results),
            )
            worker.start()
            try:
                self.assertTrue(entered.wait(15), "first writer did not reach encoder")
                contender.start()
                contender.join(15)
                self.assertEqual(contender.exitcode, 0)
                contender_outcome = results.get(timeout=5)
                self.assertTrue(
                    contender_outcome.startswith("DocumentWriteLockTimeout: document write lock"),
                    contender_outcome,
                )
                # The held writer has not changed Qdrant, and the contender
                # must not even scan while it waits for this lock.
                points = self.client.scroll(self.collection, query_filter={"must": [
                    {"key": "tenant_id", "match": {"value": "alpha"}},
                    {"key": "document_id", "match": {"value": "flock"}},
                ]}, limit=10)
                self.assertEqual({point["payload"]["text"] for point in points}, {first.content})
                release.set()
                worker.join(15)
                self.assertEqual(worker.exitcode, 0)
                self.assertEqual(results.get(timeout=5), "completed")
                following = QdrantChunkRepository(
                    self.client, collection=self.collection, embed=_fixed_vector,
                    lock_dir=directory,
                )
                following.replace_document(second, chunk_document(second))
                points = self.client.scroll(self.collection, query_filter={"must": [
                    {"key": "tenant_id", "match": {"value": "alpha"}},
                    {"key": "document_id", "match": {"value": "flock"}},
                ]}, limit=10)
                self.assertEqual({point["payload"]["text"] for point in points}, {second.content})
            finally:
                release.set()
                for process in (worker, contender):
                    if process.pid is not None:
                        process.join(2)
                        if process.is_alive():
                            process.terminate()
                            process.join(5)

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

    def test_float16_collection_refused_before_writing_real_qdrant(self) -> None:
        collection = "hermes_fp16_" + uuid.uuid4().hex[:12]
        self.client._request("PUT", f"/collections/{collection}", {
            "vectors": {"dense": {"size": 4, "distance": "Cosine", "datatype": "float16"}},
        })
        try:
            repository = QdrantChunkRepository(
                self.client, collection=collection, embed=_fixed_vector,
            )
            document = self._document("fp16", "alpha", "alice", "Texte intègre.")
            with self.assertRaisesRegex(RuntimeError, "datatype"):
                repository.replace_document(document, chunk_document(document))
            points = self.client.scroll(collection, query_filter={"must": [
                {"key": "tenant_id", "match": {"value": "alpha"}},
            ]}, limit=10)
            self.assertEqual(points, [])
        finally:
            self.client.delete_collection(collection)

    def test_hybrid_replace_reads_back_normalized_dense_and_sparse_vectors(self) -> None:
        # Hybrid preflight needs a sparse vector and the full ACL payload indexes.
        collection = "hermes_hybrid_" + uuid.uuid4().hex[:12]
        self.client.create_collection(collection, vector_size=4, sparse=True)
        try:
            specification = json.loads(INDEX_SPEC.read_text())
            for index in specification["payload_indexes"]:
                self.client.create_payload_index(
                    collection, index["field_name"], index["field_schema"]
                )
            repository = QdrantChunkRepository(
                self.client, collection=collection, embed=_fixed_vector,
                embed_hybrid=lambda _text: ([3.0, 4.0, 0.0, 0.0], {"12": 0.75, "42": 1e-7}),
            )
            first = self._document("hybrid", "alpha", "alice", "Version hybride initiale.")
            second = self._document("hybrid", "alpha", "alice", "Version hybride changée.")
            repository.replace_document(first, chunk_document(first))
            result = repository.replace_document(second, chunk_document(second))
            self.assertEqual(result.chunk_count, len(chunk_document(second)))
            points = self.client.scroll(collection, query_filter={"must": [
                {"key": "tenant_id", "match": {"value": "alpha"}},
                {"key": "document_id", "match": {"value": "hybrid"}},
            ]}, limit=10)
            self.assertEqual(len(points), result.chunk_count)
        finally:
            self.client.delete_collection(collection)

    def test_conditional_upsert_refuses_foreign_point_inserted_after_owner_scan(self) -> None:
        attempted = self._document("guide", "alpha", "alice", "Révision cible.")
        chunks = chunk_document(attempted)

        colliding = chunk_to_point(chunks[0], _fixed_vector(""))
        foreign = {**colliding, "payload": {**colliding["payload"], "owner_id": "bob"}}

        def embed_with_concurrent_insert(_text: str) -> list[float]:
            self.client.upsert(self.collection, [foreign])
            return _fixed_vector("")

        repository = QdrantChunkRepository(
            self.client, collection=self.collection, embed=embed_with_concurrent_insert,
        )
        with self.assertRaisesRegex(PermissionError, "conditional upsert"):
            repository.replace_document(attempted, chunks)
        persisted = self.client.retrieve_points(self.collection, [colliding["id"]])
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0]["payload"]["owner_id"], "bob")

    def test_conditional_upsert_refuses_mixed_owner_array_at_target_id(self) -> None:
        attempted = self._document("guide", "alpha", "alice", "Révision cible.")
        chunks = chunk_document(attempted)
        colliding = chunk_to_point(chunks[0], _fixed_vector(""))
        foreign = {**colliding, "payload": {**colliding["payload"],
                                           "owner_id": ["alice", "bob"]}}
        def embed_with_concurrent_insert(_text: str) -> list[float]:
            self.client.upsert(self.collection, [foreign])
            return _fixed_vector("")
        repository = QdrantChunkRepository(
            self.client, collection=self.collection, embed=embed_with_concurrent_insert,
        )
        with self.assertRaisesRegex(PermissionError, "conditional upsert"):
            repository.replace_document(attempted, chunks)
        persisted = self.client.retrieve_points(self.collection, [colliding["id"]])
        self.assertEqual(persisted[0]["payload"]["owner_id"], ["alice", "bob"])

    def test_replacement_keeps_array_owner_inserted_after_scan_at_unseen_id(self) -> None:
        attempted = self._document("guide", "alpha", "alice", "Révision cible.")
        old_id = str(uuid.uuid4())
        self.client.upsert(self.collection, [{
            "id": old_id, "vector": {"dense": _fixed_vector("")},
            "payload": {"tenant_id": "alpha", "document_id": "guide", "owner_id": "alice"},
        }])
        foreign_id = str(uuid.uuid4())
        foreign = {"id": foreign_id, "vector": {"dense": _fixed_vector("")},
                   "payload": {"tenant_id": "alpha", "document_id": "guide",
                               "owner_id": ["alice", "bob"]}}
        def embed_with_concurrent_insert(_text: str) -> list[float]:
            self.client.upsert(self.collection, [foreign])
            return _fixed_vector("")
        repository = QdrantChunkRepository(
            self.client, collection=self.collection, embed=embed_with_concurrent_insert,
        )
        repository.replace_document(attempted, chunk_document(attempted))
        persisted = self.client.retrieve_points(self.collection, [foreign_id, old_id])
        self.assertEqual(len(persisted), 1)  # actual stale-ID delete ran
        self.assertEqual(persisted[0]["id"], foreign_id)
        self.assertEqual(persisted[0]["payload"]["owner_id"], ["alice", "bob"])

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
