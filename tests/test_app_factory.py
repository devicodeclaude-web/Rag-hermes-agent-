from __future__ import annotations

import unittest
from unittest.mock import patch

from rag_hermes.app_factory import build_service
from rag_hermes.qdrant_preflight import QdrantPreflightError


class BuildServiceTests(unittest.TestCase):
    def test_without_qdrant_env_uses_in_memory_backend(self) -> None:
        service = build_service(env={})
        self.assertIsNone(service._repository)
        self.assertIsNone(service._generator)

    def test_generator_requires_base_url_and_model_together(self) -> None:
        for env in (
            {"RAG_GENERATOR_BASE_URL": "http://127.0.0.1:8000/v1"},
            {"RAG_GENERATOR_MODEL": "qwen-local"},
        ):
            with self.subTest(env=env):
                with self.assertRaisesRegex(ValueError, "generator"):
                    build_service(env=env)

    def test_complete_generator_env_configures_in_memory_service(self) -> None:
        service = build_service(
            env={
                "RAG_GENERATOR_BASE_URL": "http://127.0.0.1:8000/v1",
                "RAG_GENERATOR_MODEL": "qwen-local",
                "RAG_GENERATOR_API_KEY": "test-key",
            }
        )

        self.assertIsNotNone(service._generator)
        self.assertEqual(type(service._generator).__name__, "OpenAICompatibleGenerator")

    def test_top_k_defaults_to_one_and_reads_valid_env(self) -> None:
        default_service = build_service(env={})
        self.assertEqual(default_service._top_k, 1)

        configured = build_service(env={"RAG_TOP_K": "5"})
        self.assertEqual(configured._top_k, 5)

    def test_invalid_top_k_env_is_rejected(self) -> None:
        for value in ("0", "-3", "abc", "2.5"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "RAG_TOP_K"):
                    build_service(env={"RAG_TOP_K": value})

    def test_retrieval_k_defaults_and_reads_valid_env(self) -> None:
        default_service = build_service(env={})
        self.assertEqual(default_service._retrieval_k, 1)

        configured = build_service(env={"RAG_TOP_K": "3", "RAG_RETRIEVAL_K": "20"})
        self.assertEqual(configured._retrieval_k, 20)
        self.assertEqual(configured._top_k, 3)

    def test_invalid_retrieval_k_env_is_rejected(self) -> None:
        for value in ("0", "-1", "abc", "1.5"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "RAG_RETRIEVAL_K"):
                    build_service(env={"RAG_RETRIEVAL_K": value})

    def test_retrieval_k_smaller_than_top_k_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "retrieval_k"):
            build_service(env={"RAG_TOP_K": "5", "RAG_RETRIEVAL_K": "2"})

    def test_generator_api_key_whitespace_is_not_silently_stripped(self) -> None:
        malformed_credential = "TOPSECRET\n"

        with self.assertRaisesRegex(ValueError, "api_key") as captured:
            build_service(
                env={
                    "RAG_GENERATOR_BASE_URL": "http://127.0.0.1:8000/v1",
                    "RAG_GENERATOR_MODEL": "qwen-local",
                    "RAG_GENERATOR_API_KEY": malformed_credential,
                }
            )

        self.assertNotIn("TOPSECRET", str(captured.exception))

    def test_with_qdrant_url_but_no_embedder_refuses_to_start(self) -> None:
        with self.assertRaisesRegex(ValueError, "embedding"):
            build_service(
                env={"RAG_QDRANT_URL": "http://127.0.0.1:6333"},
                embed=None,
            )

    @patch("rag_hermes.app_factory.verify_collection_ready")
    def test_with_qdrant_url_and_embedder_builds_repository_backed_service(
        self, verify
    ) -> None:
        service = build_service(
            env={
                "RAG_QDRANT_URL": "http://127.0.0.1:6333",
                "RAG_QDRANT_COLLECTION": "hermes_chunks_v1",
            },
            embed=lambda text: [1.0, 0.0],
        )
        self.assertIsNotNone(service._repository)
        verify.assert_called_once()

    @patch("rag_hermes.app_factory.verify_collection_ready")
    def test_misconfigured_qdrant_collection_refuses_startup(self, verify) -> None:
        verify.side_effect = QdrantPreflightError(
            "tenant_id must declare is_tenant=true"
        )
        with self.assertRaisesRegex(QdrantPreflightError, "is_tenant"):
            build_service(
                env={"RAG_QDRANT_URL": "http://127.0.0.1:6333"},
                embed=lambda text: [1.0, 0.0],
            )

    @patch("rag_hermes.app_factory.verify_collection_ready")
    def test_embed_lock_env_builds_locked_embedder_lazily_without_loading_model(
        self, verify
    ) -> None:
        # RAG_EMBED_LOCK is an explicit operator opt-in; no model is loaded at
        # build time (lazy), so this stays offline-safe.
        service = build_service(
            env={
                "RAG_QDRANT_URL": "http://127.0.0.1:6333",
                "RAG_EMBED_LOCK": "manifests/locks/bge-m3.lock.json",
            },
        )
        self.assertIsNotNone(service._repository)
        verify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
