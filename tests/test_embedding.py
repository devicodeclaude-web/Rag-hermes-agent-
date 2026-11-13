from __future__ import annotations

import unittest

from rag_hermes.acl import Chunk
from rag_hermes.embedding import LockedBgeM3Embedder
from rag_hermes.qdrant_store import chunk_to_point


class FakeFlagModel:
    def __init__(self, vectors):
        self._vectors = vectors
        self.calls: list[str] = []

    def encode(self, texts, **kwargs):
        # FlagEmbedding returns a dict with a "dense_vecs" key.
        self.calls.append(texts if isinstance(texts, str) else list(texts))
        return {"dense_vecs": self._vectors}


class LockedBgeM3EmbedderTests(unittest.TestCase):
    def test_reads_repo_and_revision_and_dimension_from_lock(self) -> None:
        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json",
            dense_dimension=1024,
            model_loader=lambda **_: FakeFlagModel([[0.0] * 1024]),
        )

        self.assertEqual(embedder.repo_id, "BAAI/bge-m3")
        self.assertEqual(
            embedder.revision, "5617a9f61b028005a4858fdac845db406aefb181"
        )
        self.assertEqual(embedder.dense_dimension, 1024)

    def test_does_not_load_model_until_first_embed(self) -> None:
        loaded = {"count": 0}

        def loader(**_):
            loaded["count"] += 1
            return FakeFlagModel([[1.0] * 1024])

        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json",
            dense_dimension=1024,
            model_loader=loader,
        )
        self.assertEqual(loaded["count"], 0)

        vector = embedder.embed("bonjour")

        self.assertEqual(loaded["count"], 1)
        self.assertEqual(len(vector), 1024)

    def test_rejects_vector_with_wrong_dimension(self) -> None:
        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json",
            dense_dimension=1024,
            model_loader=lambda **_: FakeFlagModel([[1.0, 2.0, 3.0]]),
        )

        with self.assertRaisesRegex(ValueError, "dimension"):
            embedder.embed("bonjour")

    def test_empty_text_is_rejected(self) -> None:
        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json",
            dense_dimension=1024,
            model_loader=lambda **_: FakeFlagModel([[0.0] * 1024]),
        )

        with self.assertRaisesRegex(ValueError, "non-empty"):
            embedder.embed("   ")

    def test_dense_dimension_defaults_from_lock_when_present(self) -> None:
        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json",
            model_loader=lambda **_: FakeFlagModel([[0.0] * 1024]),
        )
        # bge-m3 is a 1024-dim dense model; the embedder must know this without
        # the caller re-declaring it.
        self.assertEqual(embedder.dense_dimension, 1024)

    def test_hybrid_embedding_uses_one_pinned_model_call_for_both_vectors(self) -> None:
        from numpy import array, float32

        class HybridModel:
            def __init__(self):
                self.calls = []

            def encode(self, texts, **kwargs):
                self.calls.append((texts, kwargs))
                return {"dense_vecs": array([[float32(0.25), float32(0.75)]]),
                        "lexical_weights": [{"12": float32(0.5), "2": float32(0.75)}]}

        model = HybridModel()
        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json", dense_dimension=2,
            model_loader=lambda **_: model,
        )
        dense, sparse = embedder.embed_hybrid("bonjour")
        self.assertEqual(dense, [0.25, 0.75])
        self.assertEqual(sparse, {"2": 0.75, "12": 0.5})
        self.assertEqual(model.calls, [(["bonjour"], {
            "return_dense": True, "return_sparse": True, "return_colbert_vecs": False,
        })])
        chunk = Chunk("alpha", "doc", "bonjour", "alpha", "private", (), (),
                      "alice", 1, 1, "a" * 64)
        point = chunk_to_point(chunk, dense, sparse_weights=sparse)
        self.assertEqual(point["vector"], {
            "dense": [0.25, 0.75],
            "sparse": {"indices": [2, 12], "values": [0.75, 0.5]},
        })

    def test_hybrid_embedding_refuses_missing_sparse_output(self) -> None:
        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json", dense_dimension=2,
            model_loader=lambda **_: FakeFlagModel([[0.25, 0.75]]),
        )
        with self.assertRaisesRegex(ValueError, "lexical_weights"):
            embedder.embed_hybrid("bonjour")

    def test_hybrid_embedding_refuses_malformed_batch_shape(self) -> None:
        class BadModel:
            def __init__(self, dense, sparse):
                self.dense, self.sparse = dense, sparse
            def encode(self, texts, **kwargs):
                return {"dense_vecs": self.dense, "lexical_weights": self.sparse}
        for dense, sparse in ((None, [{"1": 0.5}]),
                              ([[0.1, 0.2]], None),
                              ([[0.1, 0.2]], [{"1": 0.5}, {"2": 0.5}])):
            with self.subTest(dense=dense, sparse=sparse):
                embedder = LockedBgeM3Embedder(
                    lock_path="manifests/locks/bge-m3.lock.json", dense_dimension=2,
                    model_loader=lambda **_: BadModel(dense, sparse),
                )
                with self.assertRaises(ValueError):
                    embedder.embed_hybrid("bonjour")

    def test_hybrid_embedding_refuses_nonfinite_dense_values(self) -> None:
        class BadModel:
            def __init__(self, value):
                self.value = value
            def encode(self, texts, **kwargs):
                return {"dense_vecs": [[self.value, 1.0]],
                        "lexical_weights": [{"1": 0.5}]}
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                embedder = LockedBgeM3Embedder(
                    lock_path="manifests/locks/bge-m3.lock.json", dense_dimension=2,
                    model_loader=lambda **_: BadModel(value),
                )
                with self.assertRaisesRegex(ValueError, "finite"):
                    embedder.embed_hybrid("bonjour")

    def test_hybrid_embedding_rejects_coerced_dense_numbers(self) -> None:
        class BadModel:
            def __init__(self, value):
                self.value = value
            def encode(self, texts, **kwargs):
                return {"dense_vecs": [[self.value, 1.0]],
                        "lexical_weights": [{"1": 0.5}]}
        for value in ("0.5", True):
            with self.subTest(value=value):
                embedder = LockedBgeM3Embedder(
                    lock_path="manifests/locks/bge-m3.lock.json", dense_dimension=2,
                    model_loader=lambda **_: BadModel(value),
                )
                with self.assertRaisesRegex(ValueError, "dense"):
                    embedder.embed_hybrid("bonjour")

    def test_hybrid_embedding_rejects_float32_dense_overflow(self) -> None:
        class BadModel:
            def encode(self, texts, **kwargs):
                return {"dense_vecs": [[1e100, 1.0]],
                        "lexical_weights": [{"1": 0.5}]}
        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json", dense_dimension=2,
            model_loader=lambda **_: BadModel(),
        )
        with self.assertRaisesRegex(ValueError, "float32"):
            embedder.embed_hybrid("bonjour")

    def test_hybrid_embedding_rejects_mapping_and_bytes_dense_rows(self) -> None:
        class BadModel:
            def __init__(self, row):
                self.row = row
            def encode(self, texts, **kwargs):
                return {"dense_vecs": [self.row],
                        "lexical_weights": [{"1": 0.5}]}
        for row in ({0: 0.25, 1: 0.75}, bytes([1, 2]), bytearray([1, 2])):
            with self.subTest(row=row):
                embedder = LockedBgeM3Embedder(
                    lock_path="manifests/locks/bge-m3.lock.json", dense_dimension=2,
                    model_loader=lambda **_: BadModel(row),
                )
                with self.assertRaisesRegex(ValueError, "dense"):
                    embedder.embed_hybrid("bonjour")

    def test_hybrid_embedding_rejects_float32_dense_underflow(self) -> None:
        class BadModel:
            def encode(self, texts, **kwargs):
                return {"dense_vecs": [[1e-50, 1.0]],
                        "lexical_weights": [{"1": 0.5}]}
        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json", dense_dimension=2,
            model_loader=lambda **_: BadModel(),
        )
        with self.assertRaisesRegex(ValueError, "float32"):
            embedder.embed_hybrid("bonjour")

    def test_hybrid_embedding_returns_float32_rounded_dense_values(self) -> None:
        import struct
        class Model:
            def encode(self, texts, **kwargs):
                return {"dense_vecs": [[0.1, 0.0]],
                        "lexical_weights": [{"1": 0.5}]}
        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json", dense_dimension=2,
            model_loader=lambda **_: Model(),
        )
        dense, _ = embedder.embed_hybrid("bonjour")
        self.assertEqual(dense, [struct.unpack("f", struct.pack("f", 0.1))[0], 0.0])
        self.assertNotEqual(dense[0], 0.1)

    def test_hybrid_embedding_rejects_mapping_as_sparse_batch(self) -> None:
        class BadModel:
            def encode(self, texts, **kwargs):
                return {"dense_vecs": [[0.25, 0.75]],
                        "lexical_weights": {0: {"1": 0.5}}}
        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json", dense_dimension=2,
            model_loader=lambda **_: BadModel(),
        )
        with self.assertRaisesRegex(ValueError, "lexical_weights"):
            embedder.embed_hybrid("bonjour")

    def test_malformed_encode_output_raises_clear_error(self) -> None:
        class BadModel:
            def encode(self, texts, **kwargs):
                return {"wrong_key": []}

        embedder = LockedBgeM3Embedder(
            lock_path="manifests/locks/bge-m3.lock.json",
            dense_dimension=1024,
            model_loader=lambda **_: BadModel(),
        )
        with self.assertRaisesRegex(ValueError, "dense_vecs"):
            embedder.embed("bonjour")


if __name__ == "__main__":
    unittest.main()
