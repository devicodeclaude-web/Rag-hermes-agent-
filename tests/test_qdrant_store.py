import unittest

from rag_hermes.acl import Chunk
from rag_hermes.qdrant_store import chunk_to_point, deterministic_test_vector


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
        )

    def test_chunk_point_contains_complete_authorization_payload(self):
        point = chunk_to_point(self.chunk, [1.0, 0.0, 0.0, 0.0])
        payload = point["payload"]
        self.assertEqual(payload["tenant_id"], "alpha")
        self.assertEqual(payload["allowed_group_ids"], ["admins"])
        self.assertEqual(payload["allowed_user_ids"], ["alice"])
        self.assertEqual(payload["doc_version"], 3)
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

    def test_point_id_is_stable_uuid(self):
        first = chunk_to_point(self.chunk, [1.0, 0.0])
        second = chunk_to_point(self.chunk, [1.0, 0.0])
        self.assertEqual(first["id"], second["id"])
        self.assertRegex(first["id"], r"^[0-9a-f-]{36}$")

    def test_deterministic_vector_is_normalized_and_reproducible(self):
        first = deterministic_test_vector("ambre zephyr", dimensions=8)
        second = deterministic_test_vector("ambre zephyr", dimensions=8)
        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(value * value for value in first), 1.0)


if __name__ == "__main__":
    unittest.main()
