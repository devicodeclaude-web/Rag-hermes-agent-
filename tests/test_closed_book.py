from __future__ import annotations

import json
import unittest

from rag_hermes.closed_book import (
    CLOSED_BOOK_ABSTENTION,
    ClosedBookGenerator,
    GenerationError,
)


def _openai_response(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


class ClosedBookGeneratorTests(unittest.TestCase):
    def _generator(self, content, *, base_url="http://127.0.0.1:8000/v1"):
        captured = {}

        def transport(request, *, timeout):
            captured["request"] = request
            return _openai_response(content)

        gen = ClosedBookGenerator(base_url=base_url, model="local", transport=transport)
        return gen, captured

    def test_answers_from_memory_without_any_sources(self):
        gen, captured = self._generator("Paris is the capital of France.")
        answer = gen("What is the capital of France?")
        self.assertEqual(answer, "Paris is the capital of France.")
        # No sources are ever sent: the user payload has a question but no sources.
        body = json.loads(captured["request"].data.decode("utf-8"))
        user_msg = json.loads(body["messages"][-1]["content"])
        self.assertIn("question", user_msg)
        self.assertNotIn("sources", user_msg)

    def test_recognizes_exact_abstention(self):
        gen, _ = self._generator(CLOSED_BOOK_ABSTENTION)
        self.assertEqual(gen("Unknowable question?"), CLOSED_BOOK_ABSTENTION)

    def test_does_not_require_citations(self):
        # A closed-book answer has no sources, so citation markers must NOT be
        # required (unlike the RAG generator). A plain answer is accepted.
        gen, _ = self._generator("A plain answer with no [S1] markers at all.")
        self.assertEqual(gen("Q?"), "A plain answer with no [S1] markers at all.")

    def test_rejects_empty_answer(self):
        gen, _ = self._generator("   ")
        with self.assertRaises(GenerationError):
            gen("Q?")

    def test_rejects_oversized_answer(self):
        gen, _ = self._generator("x" * 20000)
        with self.assertRaises(GenerationError):
            gen("Q?")

    def test_rejects_malformed_provider_response(self):
        def transport(request, *, timeout):
            return b"{not json"

        gen = ClosedBookGenerator(
            base_url="http://127.0.0.1:8000/v1", model="local", transport=transport
        )
        with self.assertRaises(GenerationError):
            gen("Q?")

    # --- Same network hardening as the RAG generator ---

    def test_rejects_non_loopback_http_base_url(self):
        with self.assertRaises(ValueError):
            ClosedBookGenerator(base_url="http://evil.example.com/v1", model="m")

    def test_accepts_https_remote(self):
        # Constructing with HTTPS remote must not raise (no network call here).
        ClosedBookGenerator(base_url="https://api.example.com/v1", model="m")

    def test_rejects_url_with_credentials(self):
        with self.assertRaises(ValueError):
            ClosedBookGenerator(base_url="https://user:pass@api.example.com/v1", model="m")

    def test_rejects_api_key_with_control_characters(self):
        with self.assertRaises(ValueError):
            ClosedBookGenerator(
                base_url="https://api.example.com/v1", model="m", api_key="bad\nkey"
            )


if __name__ == "__main__":
    unittest.main()
