from __future__ import annotations

from collections import namedtuple
from dataclasses import replace
import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_filter import build_qdrant_filter
from rag_hermes.qdrant_preflight import QdrantPreflightError
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_store import chunk_to_point
from tests.test_qdrant_preflight import _collection


class FakeQdrantClient:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, dict]] = []
        self.upserted: list[tuple[str, list[dict]]] = []
        self.queries: list[tuple[str, list[float], dict, int]] = []
        self.query_results: list[dict] = []
        self.scrolls: list[tuple[str, dict, int]] = []
        self.scroll_results: list[dict] = []
        self.fail_upsert = False

    def delete_points(self, collection: str, query_filter: dict) -> dict:
        self.deleted.append((collection, query_filter))
        return {"status": "ok"}

    def upsert(self, collection: str, points: list[dict]) -> dict:
        if self.fail_upsert:
            raise RuntimeError("simulated Qdrant upsert failure")
        self.upserted.append((collection, points))
        return {"status": "ok"}

    def query(
        self,
        collection: str,
        vector: list[float],
        *,
        query_filter: dict,
        limit: int,
    ) -> list[dict]:
        self.queries.append((collection, vector, query_filter, limit))
        return self.query_results

    def scroll(self, collection: str, *, query_filter: dict, limit: int = 1) -> list[dict]:
        self.scrolls.append((collection, query_filter, limit))
        return self.scroll_results


class FakeHybridClient(FakeQdrantClient):
    def __init__(self) -> None:
        super().__init__()
        self.metadata = _collection()
        self.metadata["config"]["params"]["vectors"]["dense"]["size"] = 2
        self.metadata["config"]["params"]["sparse_vectors"] = {"sparse": {}}
        self.metadata_calls: list[str] = []

    def get_collection(self, collection: str) -> dict:
        self.metadata_calls.append(collection)
        return self.metadata


class QdrantSemanticsClient(FakeQdrantClient):
    """Emulate Qdrant match semantics for scalar and array payload values."""

    @staticmethod
    def _matches(payload: dict, condition: dict) -> bool:
        value = payload.get(condition["key"])
        expected = condition["match"]["value"]
        if isinstance(value, list):
            return expected in value
        return value == expected

    def scroll(self, collection: str, *, query_filter: dict, limit: int = 1) -> list[dict]:
        self.scrolls.append((collection, query_filter, limit))
        matches = []
        for point in self.scroll_results:
            payload = point.get("payload", {})
            if not all(self._matches(payload, condition) for condition in query_filter["must"]):
                continue
            if any(
                self._matches(payload, condition)
                for condition in query_filter.get("must_not", [])
            ):
                continue
            matches.append(point)
        return matches[:limit]


class QdrantChunkRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeQdrantClient()
        self.document = Document(
            document_id="guide",
            content="Installer Hermes avec pipx install hermes-agent.",
            tenant_id="alpha",
            visibility="private",
            owner_id="alice",
            allowed_groups=("support",),
            allowed_users=(),
            classification=1,
            doc_version=1,
            source_uri="local://guide",
        )
        self.repository = QdrantChunkRepository(
            self.client,
            collection="hermes_chunks_v1",
            embed=lambda text: [float(len(text)), 1.0],
        )

    def test_hybrid_ingestion_writes_both_vectors_without_changing_id_or_payload(self) -> None:
        client = FakeHybridClient()
        calls: list[str] = []
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
            embed_hybrid=lambda text: (calls.append(text) or [1.0, 0.0], {"12": 0.75}),
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        report = repository.replace_document(self.document, chunks)
        self.assertEqual(report.chunk_count, len(chunks))
        self.assertEqual(calls, [chunk.text for chunk in chunks])
        self.assertEqual(client.metadata_calls, ["hermes_chunks_v1"])
        self.assertEqual(len(client.upserted), 1)
        self.assertEqual(len(client.deleted), 1)
        for chunk, point in zip(chunks, client.upserted[0][1]):
            original = chunk_to_point(chunk, [1.0, 0.0])
            self.assertEqual((point["id"], point["payload"]),
                             (original["id"], original["payload"]))
            self.assertEqual(point["vector"], {
                "dense": [1.0, 0.0],
                "sparse": {"indices": [12], "values": [0.75]},
            })

    def test_hybrid_ingestion_rejects_foreign_chunk_before_upsert(self) -> None:
        client = FakeHybridClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
            embed_hybrid=lambda text: ([1.0, 0.0], {"12": 0.75}),
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        forged = replace(chunks[-1], tenant_id="beta")
        with self.assertRaisesRegex(ValueError, "chunk"):
            repository.replace_document(self.document, [*chunks[:-1], forged])
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])

    def test_dense_ingestion_also_rejects_foreign_chunk_before_upsert(self) -> None:
        client = FakeQdrantClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        forged = replace(chunks[0], visibility="public", allowed_groups=("all",))
        with self.assertRaisesRegex(ValueError, "chunk"):
            repository.replace_document(self.document, [forged, *chunks[1:]])
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])

    def test_ingestion_rejects_text_absent_from_the_declared_offsets(self) -> None:
        client = FakeQdrantClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        # Same document, same source_sha, same ACL: only the stored passage
        # text is forged, which a hash over the document cannot detect.
        forged = replace(chunks[0], text="classified payload")
        with self.assertRaisesRegex(ValueError, "chunk"):
            repository.replace_document(self.document, [forged, *chunks[1:]])
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])

    def test_ingestion_rejects_chunk_offsets_outside_the_document(self) -> None:
        client = FakeQdrantClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        content = self.document.content
        for start, end, text in (
            (-len(content), len(content), content),
            (0, len(content) + 50, content),
            (5, 5, ""),
            (True, len(content), content[1:]),
        ):
            with self.subTest(start=start, end=end):
                forged = replace(
                    chunks[0], text=text, start_offset=start, end_offset=end
                )
                with self.assertRaisesRegex(ValueError, "chunk"):
                    repository.replace_document(
                        self.document, [forged, *chunks[1:]]
                    )
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])

    def test_hybrid_ingestion_rejects_a_missing_sparse_vector(self) -> None:
        client = FakeHybridClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
            embed_hybrid=lambda text: ([1.0, 0.0], None),
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        with self.assertRaisesRegex(ValueError, "sparse"):
            repository.replace_document(self.document, chunks)
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])

    def test_hybrid_ingestion_rejects_a_dense_vector_of_the_wrong_size(self) -> None:
        client = FakeHybridClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
            embed_hybrid=lambda text: ([1.0, 0.0, 0.5], {"12": 0.75}),
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        with self.assertRaisesRegex(ValueError, "dense vector size"):
            repository.replace_document(self.document, chunks)
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])

    def test_hybrid_ingestion_rejects_an_encoder_that_returns_no_pair(self) -> None:
        client = FakeHybridClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
            embed_hybrid=lambda text: {"dense": [1.0, 0.0]},
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        with self.assertRaisesRegex(ValueError, "pair"):
            repository.replace_document(self.document, chunks)
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])

    def test_constructor_requires_a_sparse_vector_in_the_collection(self) -> None:
        client = FakeHybridClient()
        del client.metadata["config"]["params"]["sparse_vectors"]
        with self.assertRaises(QdrantPreflightError):
            QdrantChunkRepository(
                client, collection="hermes_chunks_v1",
                embed=lambda text: [1.0, 0.0],
                embed_hybrid=lambda text: ([1.0, 0.0], {"12": 0.75}),
            )

    def test_constructor_rejects_a_non_callable_hybrid_encoder(self) -> None:
        client = FakeHybridClient()
        with self.assertRaisesRegex(ValueError, "callable"):
            QdrantChunkRepository(
                client, collection="hermes_chunks_v1",
                embed=lambda text: [1.0, 0.0],
                embed_hybrid=[1.0, 0.0],
            )
        self.assertEqual(client.metadata_calls, [])

    def test_collection_name_verified_is_the_one_written_to(self) -> None:
        client = FakeHybridClient()
        repository = QdrantChunkRepository(
            client, collection="  hermes_chunks_v1  ",
            embed=lambda text: [1.0, 0.0],
            embed_hybrid=lambda text: ([1.0, 0.0], {"12": 0.75}),
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        repository.replace_document(self.document, chunks)
        self.assertEqual(client.metadata_calls, ["hermes_chunks_v1"])
        self.assertEqual(
            [collection for collection, _ in client.upserted], ["hermes_chunks_v1"]
        )
        self.assertEqual(
            [collection for collection, _ in client.deleted], ["hermes_chunks_v1"]
        )

    def test_ingestion_rejects_chunks_sharing_a_point_identifier(self) -> None:
        client = FakeQdrantClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        self.assertGreater(len(chunks), 1)
        # Same chunk_id, same source_sha, same doc_version: chunk_to_point
        # derives the same point ID, so one passage would overwrite the other
        # while the result still reported both.
        collided = replace(chunks[1], chunk_id=chunks[0].chunk_id)
        with self.assertRaisesRegex(ValueError, "duplicate point identifiers"):
            repository.replace_document(self.document, [chunks[0], collided])
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])

    def test_ingestion_rejects_a_forged_content_hash(self) -> None:
        client = FakeQdrantClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        # The canonical ACL barrier rejects this at read time, so accepting it
        # at write time would poison the index instead of failing closed.
        forged = replace(chunks[0], content_hash="0" * 64)
        with self.assertRaisesRegex(ValueError, "chunk"):
            repository.replace_document(self.document, [forged, *chunks[1:]])
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])

    def test_ingestion_rejects_an_acl_identifier_that_only_compares_equal(self) -> None:
        class AlwaysEqual(str):
            def __eq__(self, other: object) -> bool:
                return True

            def __ne__(self, other: object) -> bool:
                return False

            __hash__ = str.__hash__

        client = FakeQdrantClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        forged = replace(chunks[0], allowed_groups=(AlwaysEqual("everyone"),))
        with self.assertRaisesRegex(ValueError, "plain strings"):
            repository.replace_document(self.document, [forged, *chunks[1:]])
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])

    def test_ingestion_rejects_acl_mutated_while_encoding(self) -> None:
        groups = ["support"]
        document = replace(self.document, allowed_groups=groups)
        client = FakeQdrantClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1",
            embed=lambda text: groups.append("everyone") or [1.0, 0.0],
        )
        chunks = chunk_document(document, max_tokens=4, overlap_tokens=0)
        # The payload is built after the encoder returns: a caller that widens
        # the shared ACL list mid-run must not reach Qdrant.
        with self.assertRaisesRegex(ValueError, "chunk|point"):
            repository.replace_document(document, chunks)
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])

    def test_two_tenants_ingesting_the_same_document_keep_their_own_points(self) -> None:
        # Qdrant upserts by point ID: a shared ID between tenants means the
        # second write erases the first tenant's passages while both calls
        # report their full chunk_count.
        class OverwritingClient(FakeQdrantClient):
            def __init__(self) -> None:
                super().__init__()
                self.store: dict[str, dict] = {}

            def upsert(self, collection: str, points: list[dict]) -> dict:
                super().upsert(collection, points)
                for point in points:
                    self.store[point["id"]] = point
                return {"status": "ok"}

        client = OverwritingClient()
        alpha = self.document
        beta = replace(alpha, tenant_id="beta", owner_id="bob")
        for document in (alpha, beta):
            repository = QdrantChunkRepository(
                client, collection="hermes_chunks_v1",
                embed=lambda text: [1.0, 0.0],
            )
            chunks = chunk_document(document, max_tokens=4, overlap_tokens=0)
            result = repository.replace_document(document, chunks)
            self.assertEqual(result.chunk_count, len(chunks))
        chunks = chunk_document(alpha, max_tokens=4, overlap_tokens=0)
        self.assertEqual(len(client.store), 2 * len(chunks))
        self.assertEqual(
            {point["payload"]["tenant_id"] for point in client.store.values()},
            {"alpha", "beta"},
        )

    def test_replace_document_rejects_an_object_that_is_not_a_document(self) -> None:
        class DocumentLookalike:
            """Reads of owner_id flip once the ownership check is done."""

            def __init__(self) -> None:
                self._reads = 0

            def __getattr__(self, name: str) -> object:
                return getattr(self._inner, name)

            @property
            def owner_id(self) -> str:
                self._reads += 1
                return "alice" if self._reads == 1 else "bob"

        lookalike = DocumentLookalike()
        lookalike._inner = self.document
        with self.assertRaisesRegex(ValueError, "Document"):
            self.repository.replace_document(lookalike, [])
        self.assertEqual(self.client.scrolls, [])
        self.assertEqual(self.client.upserted, [])
        self.assertEqual(self.client.deleted, [])

    def test_constructor_rejects_a_non_callable_dense_encoder(self) -> None:
        with self.assertRaisesRegex(ValueError, "embed must be callable"):
            QdrantChunkRepository(
                FakeQdrantClient(), collection="hermes_chunks_v1", embed=[1.0, 0.0],
            )

    def test_dense_only_checks_the_vector_size_when_the_caller_verified_it(self) -> None:
        client = FakeQdrantClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1",
            embed=lambda text: [1.0, 0.0, 0.5], vector_size=2,
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        with self.assertRaisesRegex(ValueError, "dense vector size"):
            repository.replace_document(self.document, chunks)
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])

    def test_declared_vector_size_must_match_the_verified_collection(self) -> None:
        client = FakeHybridClient()
        with self.assertRaisesRegex(ValueError, "vector_size"):
            QdrantChunkRepository(
                client, collection="hermes_chunks_v1",
                embed=lambda text: [1.0, 0.0],
                embed_hybrid=lambda text: ([1.0, 0.0], {"12": 0.75}),
                vector_size=1024,
            )
        for size in (0, -1, True, 2.0, "2"):
            with self.subTest(size=size), self.assertRaisesRegex(
                ValueError, "vector_size"
            ):
                QdrantChunkRepository(
                    FakeQdrantClient(), collection="hermes_chunks_v1",
                    embed=lambda text: [1.0, 0.0], vector_size=size,
                )

    def test_hybrid_encoder_may_return_a_named_tuple_pair(self) -> None:
        pair = namedtuple("HybridVectors", "dense sparse")
        client = FakeHybridClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
            embed_hybrid=lambda text: pair([1.0, 0.0], {"12": 0.75}),
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        result = repository.replace_document(self.document, chunks)
        self.assertEqual(result.chunk_count, len(chunks))
        self.assertEqual(len(client.upserted), 1)

    def test_hybrid_encoder_may_return_a_list_pair(self) -> None:
        client = FakeHybridClient()
        repository = QdrantChunkRepository(
            client, collection="hermes_chunks_v1", embed=lambda text: [1.0, 0.0],
            embed_hybrid=lambda text: [[1.0, 0.0], {"12": 0.75}],
        )
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)
        result = repository.replace_document(self.document, chunks)
        self.assertEqual(result.chunk_count, len(chunks))
        self.assertEqual(len(client.upserted), 1)

    def test_replace_document_upserts_new_chunks_before_deleting_stale_points(self) -> None:
        chunks = chunk_document(self.document, max_tokens=4, overlap_tokens=0)

        result = self.repository.replace_document(self.document, chunks)

        self.assertEqual(result.document_id, "guide")
        self.assertEqual(result.chunk_count, len(chunks))
        # Upsert happens first (compensating order), then a scoped delete.
        collection, points = self.client.upserted[0]
        self.assertEqual(collection, "hermes_chunks_v1")
        self.assertEqual(len(points), len(chunks))
        self.assertTrue(all(point["payload"]["owner_id"] == "alice" for point in points))
        new_ids = [point["id"] for point in points]
        self.assertEqual(
            self.client.deleted,
            [
                (
                    "hermes_chunks_v1",
                    {
                        "must": [
                            {"key": "tenant_id", "match": {"value": "alpha"}},
                            {"key": "document_id", "match": {"value": "guide"}},
                        ],
                        "must_not": [{"has_id": new_ids}],
                    },
                )
            ],
        )

    def test_search_prefilters_in_qdrant_and_postfilters_returned_candidates(self) -> None:
        alpha_chunk = chunk_document(self.document)[0]
        beta_document = Document(
            document_id="beta-secret",
            content="Installer le secret Beta.",
            tenant_id="beta",
            visibility="private",
            owner_id="bob",
            allowed_groups=(),
            allowed_users=(),
            classification=1,
            doc_version=1,
            source_uri="local://beta",
        )
        beta_chunk = chunk_document(beta_document)[0]
        alpha_point = chunk_to_point(alpha_chunk, [1.0, 0.0])
        beta_point = chunk_to_point(beta_chunk, [1.0, 0.0])
        alpha_point["score"] = 0.8
        beta_point["score"] = 0.99
        self.client.query_results = [beta_point, alpha_point]
        context = AuthorizationContext("alpha", "alice", ("support",), 1)

        results = self.repository.search("Installer Hermes", context=context, limit=5)

        self.assertEqual(
            self.client.queries,
            [
                (
                    "hermes_chunks_v1",
                    [16.0, 1.0],
                    build_qdrant_filter(context),
                    5,
                )
            ],
        )
        self.assertEqual([result.chunk.document_id for result in results], ["guide"])
        self.assertEqual(results[0].score, 0.8)

    def test_search_rejects_missing_or_invalid_score_before_abstention(self) -> None:
        chunk = chunk_document(self.document)[0]
        context = AuthorizationContext("alpha", "alice", ("support",), 1)
        for score in (None, True, "0.9", float("nan"), float("inf")):
            with self.subTest(score=score):
                point = chunk_to_point(chunk, [1.0, 0.0])
                if score is not None:
                    point["score"] = score
                self.client.query_results = [point]
                with self.assertRaisesRegex(ValueError, "candidate score"):
                    self.repository.search("Installer Hermes", context=context)

    def test_failed_upsert_does_not_delete_existing_document(self) -> None:
        chunks = chunk_document(self.document)
        self.client.fail_upsert = True

        with self.assertRaisesRegex(RuntimeError, "upsert failure"):
            self.repository.replace_document(self.document, chunks)

        self.assertEqual(self.client.deleted, [])

    def test_replace_refuses_persisted_different_owner_before_any_mutation(self) -> None:
        self.client.scroll_results = [
            {
                "id": "existing-point",
                "payload": {
                    "tenant_id": "alpha",
                    "document_id": "guide",
                    "owner_id": "alice",
                },
            }
        ]
        hijacked = Document(
            document_id="guide",
            content="Tentative de remplacement.",
            tenant_id="alpha",
            visibility="private",
            owner_id="bob",
            allowed_groups=("support",),
            allowed_users=(),
            classification=1,
            doc_version=2,
            source_uri="local://hijacked",
        )

        with self.assertRaisesRegex(PermissionError, "owner"):
            self.repository.replace_document(hijacked, chunk_document(hijacked))

        self.assertEqual(
            self.client.scrolls,
            [
                (
                    "hermes_chunks_v1",
                    {
                        "must": [
                            {"key": "tenant_id", "match": {"value": "alpha"}},
                            {"key": "document_id", "match": {"value": "guide"}},
                        ],
                    },
                    10_000,
                )
            ],
        )
        self.assertEqual(self.client.upserted, [])
        self.assertEqual(self.client.deleted, [])

    def test_replace_refuses_array_owner_payload_before_any_mutation(self) -> None:
        client = QdrantSemanticsClient()
        client.scroll_results = [
            {
                "id": "corrupt-point",
                "payload": {
                    "tenant_id": "alpha",
                    "document_id": "guide",
                    "owner_id": ["alice", "bob"],
                },
            }
        ]
        embed_calls: list[str] = []
        repository = QdrantChunkRepository(
            client,
            collection="hermes_chunks_v1",
            embed=lambda text: embed_calls.append(text) or [1.0, 1.0],
        )
        hijacked = Document(
            document_id="guide",
            content="Tentative de remplacement.",
            tenant_id="alpha",
            visibility="private",
            owner_id="bob",
            allowed_groups=("support",),
            allowed_users=(),
            classification=1,
            doc_version=2,
            source_uri="local://hijacked",
        )

        with self.assertRaisesRegex(PermissionError, "owner"):
            repository.replace_document(hijacked, chunk_document(hijacked))

        self.assertEqual(embed_calls, [])
        self.assertEqual(client.upserted, [])
        self.assertEqual(client.deleted, [])


if __name__ == "__main__":
    unittest.main()
