from __future__ import annotations

import unittest

from rag_hermes.app_factory import build_service


class BuildServiceTests(unittest.TestCase):
    def test_without_qdrant_env_uses_in_memory_backend(self) -> None:
        service = build_service(env={})
        self.assertIsNone(service._repository)

    def test_with_qdrant_url_but_no_embedder_refuses_to_start(self) -> None:
        with self.assertRaisesRegex(ValueError, "embedding"):
            build_service(
                env={"RAG_QDRANT_URL": "http://127.0.0.1:6333"},
                embed=None,
            )

    def test_with_qdrant_url_and_embedder_builds_repository_backed_service(self) -> None:
        service = build_service(
            env={
                "RAG_QDRANT_URL": "http://127.0.0.1:6333",
                "RAG_QDRANT_COLLECTION": "hermes_chunks_v1",
            },
            embed=lambda text: [1.0, 0.0],
        )
        self.assertIsNotNone(service._repository)

    def test_embed_lock_env_builds_locked_embedder_lazily_without_loading_model(self) -> None:
        # RAG_EMBED_LOCK is an explicit operator opt-in; no model is loaded at
        # build time (lazy), so this stays offline-safe.
        service = build_service(
            env={
                "RAG_QDRANT_URL": "http://127.0.0.1:6333",
                "RAG_EMBED_LOCK": "manifests/locks/bge-m3.lock.json",
            },
        )
        self.assertIsNotNone(service._repository)


if __name__ == "__main__":
    unittest.main()
