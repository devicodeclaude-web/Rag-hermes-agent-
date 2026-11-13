from dataclasses import replace
import importlib
import unittest

from rag_hermes.acl import Chunk
from rag_hermes.qdrant_store import chunk_to_point, deterministic_test_vector, lexical_weights_to_sparse_vector


class QdrantStoreTests(unittest.TestCase):
    def setUp(self):
        self.chunk = Chunk(
            chunk_id="chunk-alpha-1",
            document_id="doc-alpha",
            text="ambre zephyr",
            tenant_id="alpha",
            visibility="private",
            allowed_groups=("admins",),
            allowed_users=("alice",),
            owner_id="alice",
            classification=2,
            doc_version=3,
            source_sha="a" * 64,
            source_uri="synthetic://alpha/doc.md",
            section="Installation",
            start_offset=10,
            end_offset=42,
            token_count=17,
            tokenizer_name="BAAI/bge-reranker-v2-m3",
            tokenizer_revision="953dc6f",
            content_hash="a" * 64,
            acl_version=11,
        )

    def test_chunk_point_contains_complete_authorization_payload(self):
        point = chunk_to_point(self.chunk, [1.0, 0.0, 0.0, 0.0])
        payload = point["payload"]
        self.assertEqual(payload["tenant_id"], "alpha")
        self.assertEqual(payload["allowed_group_ids"], ["admins"])
        self.assertEqual(payload["allowed_user_ids"], ["alice"])
        self.assertEqual(payload["doc_version"], 3)
        self.assertEqual(payload["acl_version"], 11)
        self.assertEqual(payload["source_sha"], "a" * 64)
        self.assertEqual(payload["section"], "Installation")
        self.assertEqual(payload["start_offset"], 10)
        self.assertEqual(payload["end_offset"], 42)
        self.assertEqual(payload["token_count"], 17)
        self.assertEqual(payload["tokenizer_name"], "BAAI/bge-reranker-v2-m3")
        self.assertEqual(payload["tokenizer_revision"], "953dc6f")
        self.assertEqual(payload["content_hash"], "a" * 64)
        self.assertFalse(payload["tombstone"])
        self.assertEqual(point["vector"]["dense"], [1.0, 0.0, 0.0, 0.0])

    def test_chunk_point_can_include_bge_sparse_vector_without_changing_identity(self):
        dense_only = chunk_to_point(self.chunk, [1.0, 0.0])
        hybrid = chunk_to_point(self.chunk, [1.0, 0.0], sparse_weights={"9": 0.7})
        self.assertEqual(hybrid["id"], dense_only["id"])
        self.assertEqual(hybrid["payload"], dense_only["payload"])
        self.assertEqual(hybrid["vector"], {
            "dense": [1.0, 0.0], "sparse": {"indices": [9], "values": [0.7]},
        })

    def test_bge_lexical_weights_encode_as_sorted_qdrant_sparse_vector(self):
        self.assertEqual(
            lexical_weights_to_sparse_vector({"12": 0.75, "2": 0.5}),
            {"indices": [2, 12], "values": [0.5, 0.75]},
        )

    def test_bge_numpy_float32_weights_are_supported(self):
        try:
            float32 = importlib.import_module("numpy").float32
        except ImportError:
            self.skipTest("numpy absent")
        self.assertEqual(
            lexical_weights_to_sparse_vector({"7": float32(0.25)}),
            {"indices": [7], "values": [0.25]},
        )

    def test_sparse_vector_rejects_mapping_with_duplicate_token_ids(self):
        from collections.abc import Mapping
        class DuplicateIds(Mapping):
            def __iter__(self):
                return iter(("1", "1"))
            def __len__(self):
                return 2
            def __getitem__(self, key):
                return 0.5
        with self.assertRaises(ValueError):
            lexical_weights_to_sparse_vector(DuplicateIds())

    def test_sparse_vector_rejects_mapping_without_iterable_entries(self):
        from collections.abc import Mapping
        class InconsistentMapping(Mapping):
            def __iter__(self):
                return iter(())
            def __len__(self):
                return 1
            def __getitem__(self, key):
                raise KeyError(key)
        with self.assertRaises(ValueError):
            lexical_weights_to_sparse_vector(InconsistentMapping())

    def test_sparse_vector_rejects_float32_underflow_overflow_and_large_integer(self):
        for value in (1e-50, 1e100, 10**400):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lexical_weights_to_sparse_vector({"1": value})

    def test_sparse_vector_rejects_ambiguous_ids_and_invalid_weights(self):
        for weights in ({}, {"01": 1.0}, {"-1": 1.0}, {"4294967296": 1.0},
                        {"2": True}, {"2": "0.5"}, {"2": float("nan")},
                        {"2": float("inf")}, {"1": 0.0}, {"1": -0.1}):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                lexical_weights_to_sparse_vector(weights)

    def test_vector_must_be_a_nonempty_list_or_tuple(self):
        class FakeArray(list):
            def __bool__(self):
                raise ValueError("truth value is ambiguous")

        for vector in ([], FakeArray([1.0, 0.0]), "ab", {"dense": [1.0]}, None):
            with self.subTest(vector=type(vector).__name__):
                with self.assertRaisesRegex(ValueError, "nonempty list or tuple"):
                    chunk_to_point(self.chunk, vector)

    def test_point_id_uses_the_same_string_for_length_and_body(self):
        from rag_hermes.qdrant_store import stable_point_id

        class OddIdentifier:
            def __str__(self):
                return "AB"

            def __format__(self, spec):
                return "xy"

        shared = dict(
            document_id="guide", chunk_id="passage", source_sha="a" * 64,
            doc_version=1,
        )
        self.assertEqual(
            stable_point_id(tenant_id=OddIdentifier(), **shared),
            stable_point_id(tenant_id="AB", **shared),
        )
        self.assertNotEqual(
            stable_point_id(tenant_id=OddIdentifier(), **shared),
            stable_point_id(tenant_id="xy", **shared),
        )

    def test_point_id_key_is_injective_across_field_boundaries(self):
        from rag_hermes.qdrant_store import stable_point_id

        # A plain separator moves the boundary between two fields as soon as a
        # field contains it, and document_id comes from the client.
        for first, second in (
            (
                dict(tenant_id="t", document_id="rapport\x1f2024", chunk_id="CHUNKV"),
                dict(tenant_id="t", document_id="rapport", chunk_id="2024\x1fCHUNKV"),
            ),
            (
                dict(tenant_id="t\x1fx", document_id="doc", chunk_id="c"),
                dict(tenant_id="t", document_id="x\x1fdoc", chunk_id="c"),
            ),
        ):
            with self.subTest(first=first):
                common = {"source_sha": "a" * 64, "doc_version": 1}
                self.assertNotEqual(
                    stable_point_id(**first, **common),
                    stable_point_id(**second, **common),
                )

    def test_point_id_is_stable_uuid(self):
        first = chunk_to_point(self.chunk, [1.0, 0.0])
        second = chunk_to_point(self.chunk, [1.0, 0.0])
        self.assertEqual(first["id"], second["id"])
        self.assertRegex(first["id"], r"^[0-9a-f-]{36}$")

    def test_point_id_is_bound_to_the_tenant_and_the_document(self):
        reference = chunk_to_point(self.chunk, [1.0, 0.0])["id"]
        # chunk_id is a hash of document_id/doc_version/index/source_sha only,
        # so without the tenant and document in the key two tenants ingesting
        # the same document at the same version derive the same point ID and
        # the second upsert silently erases the first tenant's passages.
        for field, value in (
            ("tenant_id", "beta"),
            ("document_id", "autre"),
            ("chunk_id", "0" * 24),
            ("source_sha", "1" * 64),
            ("doc_version", self.chunk.doc_version + 1),
        ):
            with self.subTest(field=field):
                other = chunk_to_point(
                    replace(self.chunk, **{field: value}), [1.0, 0.0]
                )
                self.assertNotEqual(other["id"], reference)


    def test_deterministic_vector_is_normalized_and_reproducible(self):
        first = deterministic_test_vector("ambre zephyr", dimensions=8)
        second = deterministic_test_vector("ambre zephyr", dimensions=8)
        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(value * value for value in first), 1.0)


if __name__ == "__main__":
    unittest.main()
