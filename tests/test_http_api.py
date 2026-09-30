from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
from typing import Any
import unittest

from rag_hermes.http_api import make_app
from rag_hermes.generator import GenerationError, OpenAICompatibleGenerator
from rag_hermes.service import RagService


def request(
    app,
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    content_type: str = "application/json",
    host: str = "localhost:8080",
) -> tuple[str, dict[str, str], Any]:
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
        "wsgi.input": BytesIO(body),
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8080",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "HTTP_HOST": host,
    }
    captured: dict[str, Any] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    response_body = b"".join(app(environ, start_response))
    content_type = captured["headers"].get("Content-Type", "")
    data = json.loads(response_body) if "application/json" in content_type else response_body.decode("utf-8")
    return captured["status"], captured["headers"], data


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = make_app(RagService())
        self.context = {
            "tenant_id": "alpha",
            "user_id": "alice",
            "groups": ["support"],
            "clearance": 1,
        }

    def test_import_then_question_over_http_returns_citation(self) -> None:
        import_status, _, imported = request(
            self.app,
            "POST",
            "/api/documents",
            {
                "context": self.context,
                "document": {
                    "document_id": "guide-installation",
                    "content": "Pour installer Hermes, utilisez pipx install hermes-agent.",
                    "tenant_id": "alpha",
                    "visibility": "private",
                    "owner_id": "alice",
                    "allowed_groups": ["support"],
                    "allowed_users": [],
                    "classification": 1,
                    "doc_version": 1,
                    "source_uri": "file:///docs/guide.md",
                },
            },
        )
        answer_status, _, answered = request(
            self.app,
            "POST",
            "/api/questions",
            {"context": self.context, "question": "Comment installer Hermes ?"},
        )

        self.assertEqual(import_status, "201 Created")
        self.assertEqual(imported["document_id"], "guide-installation")
        self.assertEqual(answer_status, "200 OK")
        self.assertFalse(answered["abstained"])
        self.assertEqual(answered["citations"][0]["document_id"], "guide-installation")

    def test_generator_failure_returns_bad_gateway_not_abstention(self) -> None:
        def fail_generator(question, evidence):
            raise GenerationError("provider unavailable")

        service = RagService(generator=fail_generator)
        app = make_app(service)
        document = {
            "document_id": "guide",
            "content": "Hermes s'installe avec pipx install hermes-agent.",
            "tenant_id": "alpha",
            "visibility": "private",
            "owner_id": "alice",
            "allowed_groups": ["support"],
            "allowed_users": [],
            "classification": 1,
            "doc_version": 1,
            "source_uri": "local://guide",
        }
        request(
            app,
            "POST",
            "/api/documents",
            {"context": self.context, "document": document},
        )

        status, _, response = request(
            app,
            "POST",
            "/api/questions",
            {"context": self.context, "question": "Comment installer Hermes ?"},
        )

        self.assertEqual(status, "502 Bad Gateway")
        self.assertEqual(response, {"error": "generation_failed"})

    def test_reranker_failure_returns_bad_gateway_not_bad_request(self) -> None:
        # A reranker returning the wrong number of scores is a server-side
        # component failure. It must surface as 502 (generation_failed), never
        # as a 400 that would misattribute the fault to the client request.
        def broken_reranker(question, chunks):
            return [1.0]  # wrong length when more than one candidate

        def generate(question, evidence):
            return "Réponse [S1]."

        service = RagService(
            generator=generate,
            reranker=broken_reranker,
            retrieval_k=10,
            top_k=2,
        )
        app = make_app(service)
        for suffix in ("un", "deux"):
            document = {
                "document_id": f"guide-{suffix}",
                "content": f"Hermes s'installe avec la methode {suffix}.",
                "tenant_id": "alpha",
                "visibility": "private",
                "owner_id": "alice",
                "allowed_groups": ["support"],
                "allowed_users": [],
                "classification": 1,
                "doc_version": 1,
                "source_uri": f"local://guide-{suffix}",
            }
            request(
                app,
                "POST",
                "/api/documents",
                {"context": self.context, "document": document},
            )

        status, _, response = request(
            app,
            "POST",
            "/api/questions",
            {"context": self.context, "question": "Comment installer Hermes ?"},
        )

        self.assertEqual(status, "502 Bad Gateway")
        self.assertEqual(response, {"error": "generation_failed"})

    def test_oversized_citation_marker_returns_generic_bad_gateway(self) -> None:
        content = "Réponse [S" + "9" * 10_000 + "]."
        raw = json.dumps(
            {"choices": [{"message": {"content": content}}]}
        ).encode("utf-8")
        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8000/v1",
            model="qwen-local",
            transport=lambda request, timeout: raw,
        )
        app = make_app(RagService(generator=generator))
        document = {
            "document_id": "guide",
            "content": "Hermes s'installe avec pipx install hermes-agent.",
            "tenant_id": "alpha",
            "visibility": "private",
            "owner_id": "alice",
            "allowed_groups": ["support"],
            "allowed_users": [],
            "classification": 1,
            "doc_version": 1,
            "source_uri": "local://guide",
        }
        request(
            app,
            "POST",
            "/api/documents",
            {"context": self.context, "document": document},
        )

        status, _, response = request(
            app,
            "POST",
            "/api/questions",
            {"context": self.context, "question": "Comment installer Hermes ?"},
        )

        self.assertEqual(status, "502 Bad Gateway")
        self.assertEqual(response, {"error": "generation_failed"})

    def test_generator_answer_without_resolved_citation_returns_bad_gateway(self) -> None:
        def generate(question, evidence):
            return "Réponse non fondée sans marqueur de source."

        app = make_app(RagService(generator=generate))
        document = {
            "document_id": "guide",
            "content": "Hermes s'installe avec pipx install hermes-agent.",
            "tenant_id": "alpha",
            "visibility": "private",
            "owner_id": "alice",
            "allowed_groups": ["support"],
            "allowed_users": [],
            "classification": 1,
            "doc_version": 1,
            "source_uri": "local://guide",
        }
        request(
            app,
            "POST",
            "/api/documents",
            {"context": self.context, "document": document},
        )

        status, _, response = request(
            app,
            "POST",
            "/api/questions",
            {"context": self.context, "question": "Comment installer Hermes ?"},
        )

        self.assertEqual(status, "502 Bad Gateway")
        self.assertEqual(response, {"error": "generation_failed"})

    def test_home_page_exposes_mobile_import_and_question_interface(self) -> None:
        status, headers, html = request(self.app, "GET", "/")

        self.assertEqual(status, "200 OK")
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn('name="viewport"', html)
        self.assertIn('id="document-form"', html)
        self.assertIn('id="question-form"', html)

    def test_mutating_route_rejects_non_json_content_type(self) -> None:
        status, _, response = request(
            self.app,
            "POST",
            "/api/questions",
            {"context": self.context, "question": "Bonjour"},
            content_type="text/plain",
        )

        self.assertEqual(status, "415 Unsupported Media Type")
        self.assertEqual(response["error"], "unsupported_media_type")

    def test_request_rejects_untrusted_host_header(self) -> None:
        status, _, response = request(
            self.app,
            "GET",
            "/",
            host="attacker.example",
        )

        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(response["error"], "invalid_host")

        ipv6_suffix_status, _, ipv6_suffix_response = request(
            self.app,
            "GET",
            "/",
            host="[::1]evil.example",
        )
        self.assertEqual(ipv6_suffix_status, "400 Bad Request")
        self.assertEqual(ipv6_suffix_response["error"], "invalid_host")

    def test_known_api_route_rejects_wrong_method_with_allow_header(self) -> None:
        status, headers, response = request(self.app, "GET", "/api/questions")

        self.assertEqual(status, "405 Method Not Allowed")
        self.assertEqual(headers["Allow"], "POST")
        self.assertEqual(response["error"], "method_not_allowed")

    def test_oversized_body_returns_payload_too_large(self) -> None:
        status, _, response = request(
            self.app,
            "POST",
            "/api/questions",
            {"question": "x" * 1_000_000, "context": self.context},
        )

        self.assertEqual(status, "413 Payload Too Large")
        self.assertEqual(response["error"], "payload_too_large")

    def test_question_rejects_invalid_identity_types_and_empty_question(self) -> None:
        invalid_payloads = []
        for field, value in (
            ("tenant_id", None),
            ("user_id", ["alice"]),
            ("groups", "support"),
            ("clearance", True),
        ):
            context = deepcopy(self.context)
            context[field] = value
            invalid_payloads.append(
                (field, {"context": context, "question": "Bonjour"})
            )
        invalid_payloads.append(
            ("question", {"context": self.context, "question": "   "})
        )

        for field, payload in invalid_payloads:
            with self.subTest(field=field):
                status, _, response = request(
                    self.app,
                    "POST",
                    "/api/questions",
                    payload,
                )
                self.assertEqual(status, "400 Bad Request")
                self.assertEqual(response["error"], "invalid_request")

    def test_document_rejects_invalid_acl_types_and_empty_values(self) -> None:
        document = {
            "document_id": "guide",
            "content": "Contenu valide",
            "tenant_id": "alpha",
            "visibility": "private",
            "owner_id": "alice",
            "allowed_groups": ["support"],
            "allowed_users": [],
            "classification": 1,
            "doc_version": 1,
            "source_uri": "local://guide",
        }
        invalid_values = (
            ("document_id", None),
            ("content", "   "),
            ("allowed_groups", "support"),
            ("allowed_users", None),
            ("classification", False),
            ("doc_version", True),
        )

        for field, value in invalid_values:
            with self.subTest(field=field):
                invalid_document = deepcopy(document)
                invalid_document[field] = value
                status, _, response = request(
                    self.app,
                    "POST",
                    "/api/documents",
                    {"context": self.context, "document": invalid_document},
                )
                self.assertEqual(status, "400 Bad Request")
                self.assertEqual(response["error"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
