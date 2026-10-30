from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from http.client import BadStatusLine
import threading
import unittest

from rag_hermes.acl import Chunk
from rag_hermes.generator import GenerationError, OpenAICompatibleGenerator


class CapturingTransport:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls = []

    def __call__(self, request, *, timeout: float) -> bytes:
        self.calls.append((request, timeout))
        return json.dumps(self.response).encode("utf-8")


def unavailable_transport(request, *, timeout: float) -> bytes:
    raise OSError("connection refused")


def evidence_chunk() -> Chunk:
    return Chunk(
        chunk_id="guide:1",
        document_id="guide",
        text="Installez Hermes avec pipx install hermes-agent.",
        tenant_id="alpha",
        visibility="private",
        owner_id="alice",
        allowed_groups=("support",),
        allowed_users=(),
        classification=1,
        acl_version=1,
        doc_version=1,
        source_sha="a" * 64,
        source_uri="file:///guide.md",
    )


class OpenAICompatibleGeneratorTests(unittest.TestCase):
    def test_api_key_with_control_character_is_rejected_without_echoing_secret(self) -> None:
        malformed_credential = "TOPSECRET\nINJECTED"

        with self.assertRaisesRegex(ValueError, "api_key") as captured:
            OpenAICompatibleGenerator(
                base_url="http://127.0.0.1:8000/v1",
                model="qwen-local",
                api_key=malformed_credential,
            )

        self.assertNotIn("TOPSECRET", str(captured.exception))
        self.assertNotIn("INJECTED", str(captured.exception))

    def test_redirect_is_refused_before_api_key_can_reach_another_host(self) -> None:
        received_authorization = []

        class DestinationHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                received_authorization.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        destination = HTTPServer(("127.0.0.1", 0), DestinationHandler)
        destination_thread = threading.Thread(
            target=destination.serve_forever, daemon=True
        )
        destination_thread.start()

        location = f"http://127.0.0.1:{destination.server_address[1]}/captured"

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header("Location", location)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        redirect = HTTPServer(("127.0.0.1", 0), RedirectHandler)
        redirect_thread = threading.Thread(target=redirect.serve_forever, daemon=True)
        redirect_thread.start()
        try:
            generator = OpenAICompatibleGenerator(
                base_url=f"http://127.0.0.1:{redirect.server_address[1]}/v1",
                model="qwen-local",
                api_key="placeholder-generator-key",
            )
            with self.assertRaises(GenerationError):
                generator("Question", (evidence_chunk(),))
            self.assertEqual(received_authorization, [])
        finally:
            redirect.shutdown()
            destination.shutdown()
            redirect.server_close()
            destination.server_close()
            redirect_thread.join()
            destination_thread.join()

    def test_rejects_insecure_or_ambiguous_provider_urls(self) -> None:
        invalid_urls = (
            "http://api.example.com/v1",
            "ftp://127.0.0.1/v1",
            "https://user:password@api.example.com/v1",
            "https://api.example.com/v1?tenant=alpha",
            "https://api.example.com/v1#fragment",
        )
        for base_url in invalid_urls:
            with self.subTest(base_url=base_url):
                with self.assertRaisesRegex(ValueError, "base_url"):
                    OpenAICompatibleGenerator(base_url=base_url, model="model")

    def test_sends_grounded_prompt_and_returns_text(self) -> None:
        transport = CapturingTransport(
            {"choices": [{"message": {"content": "Utilisez pipx [S1]."}}]}
        )
        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8000/v1",
            model="qwen-local",
            api_key="placeholder-generator-key",
            transport=transport,
        )

        answer = generator("Comment installer Hermes ?", (evidence_chunk(),))

        self.assertEqual(answer, "Utilisez pipx [S1].")
        request, timeout = transport.calls[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8000/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer placeholder-generator-key")
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "qwen-local")
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["max_tokens"], 512)
        prompt = payload["messages"][1]["content"]
        structured = json.loads(prompt)
        self.assertEqual(structured["question"], "Comment installer Hermes ?")
        self.assertEqual(structured["sources"][0]["id"], "S1")
        self.assertIn("pipx install hermes-agent", structured["sources"][0]["text"])
        self.assertNotIn("source_uri", structured["sources"][0])
        self.assertNotIn("file:///guide.md", prompt)
        self.assertEqual(timeout, 60.0)

    def test_malformed_or_empty_provider_response_fails_closed(self) -> None:
        invalid_responses = (
            {},
            {"choices": []},
            {"choices": [{"message": {"content": "   "}}]},
            {"choices": [{"message": {"content": ["not", "text"]}}]},
        )
        for response in invalid_responses:
            with self.subTest(response=response):
                generator = OpenAICompatibleGenerator(
                    base_url="http://127.0.0.1:8000/v1",
                    model="qwen-local",
                    transport=CapturingTransport(response),
                )
                with self.assertRaisesRegex(GenerationError, "response"):
                    generator("Question", (evidence_chunk(),))

    def test_json_parser_resource_limit_failure_is_normalized(self) -> None:
        class PathologicalJsonTransport:
            def __call__(self, request, *, timeout):
                return (
                    b'{"request_id":'
                    + b"9" * 10_000
                    + b',"choices":[{"message":{"content":"ok [S1]"}}]}'
                )

        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8000/v1",
            model="qwen-local",
            transport=PathologicalJsonTransport(),
        )

        with self.assertRaisesRegex(GenerationError, "response"):
            generator("Question", (evidence_chunk(),))

    def test_oversized_provider_response_is_refused_before_parsing(self) -> None:
        class OversizedTransport:
            def __call__(self, request, *, timeout):
                return b"x" * 1_000_001

        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8000/v1",
            model="qwen-local",
            transport=OversizedTransport(),
        )

        with self.assertRaisesRegex(GenerationError, "too large"):
            generator("Question", (evidence_chunk(),))

    def test_oversized_answer_content_is_refused_after_parsing(self) -> None:
        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8000/v1",
            model="qwen-local",
            transport=CapturingTransport(
                {
                    "choices": [
                        {"message": {"content": "x" * 16_385 + " [S1]"}}
                    ]
                }
            ),
        )

        with self.assertRaisesRegex(GenerationError, "content is too large"):
            generator("Question", (evidence_chunk(),))

    def test_transport_failure_is_normalized_without_leaking_provider_detail(self) -> None:
        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8000/v1",
            model="qwen-local",
            transport=unavailable_transport,
        )

        with self.assertRaisesRegex(GenerationError, "unavailable") as captured:
            generator("Question", (evidence_chunk(),))

        self.assertNotIn("connection refused", str(captured.exception))

    def test_http_protocol_failure_is_normalized(self) -> None:
        def fail(request, *, timeout):
            raise BadStatusLine("not-http")

        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8000/v1",
            model="qwen-local",
            transport=fail,
        )

        with self.assertRaisesRegex(GenerationError, "unavailable"):
            generator("Question", (evidence_chunk(),))

    def test_transport_error_resource_is_closed(self) -> None:
        class ClosableTransportError(OSError):
            def __init__(self):
                super().__init__("provider error")
                self.closed = False

            def close(self):
                self.closed = True

        error = ClosableTransportError()

        def fail(request, *, timeout):
            raise error

        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8000/v1",
            model="qwen-local",
            transport=fail,
        )

        with self.assertRaises(GenerationError):
            generator("Question", (evidence_chunk(),))

        self.assertTrue(error.closed)

    def test_non_abstaining_answer_requires_valid_source_marker(self) -> None:
        invalid_answers = (
            "Utilisez pipx.",
            "Utilisez pipx [S2].",
            "Utilisez pipx [S" + "9" * 10_000 + "].",
        )
        for answer in invalid_answers:
            with self.subTest(answer=answer):
                generator = OpenAICompatibleGenerator(
                    base_url="http://127.0.0.1:8000/v1",
                    model="qwen-local",
                    transport=CapturingTransport(
                        {"choices": [{"message": {"content": answer}}]}
                    ),
                )
                with self.assertRaisesRegex(GenerationError, "citation"):
                    generator("Question", (evidence_chunk(),))


if __name__ == "__main__":
    unittest.main()
