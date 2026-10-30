from __future__ import annotations

import unittest

from rag_hermes.embedding import LockedBgeM3Embedder


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
