from __future__ import annotations

from io import BytesIO
import json
import unittest

from rag_hermes.http_api import make_app
from rag_hermes.service import RagService


def request(
    app,
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    content_type: str = "application/json",
    host: str = "localhost:8080",
):
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
    captured: dict[str, object] = {}

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


if __name__ == "__main__":
    unittest.main()
