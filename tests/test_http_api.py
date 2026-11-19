from __future__ import annotations

from io import BytesIO
import json
from typing import Any
import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.auth import TokenAuthenticator
from rag_hermes.http_api import make_app
from rag_hermes.generator import GenerationError, OpenAICompatibleGenerator
from rag_hermes.reranker_budget import RerankerBudgetExceeded
from rag_hermes.service import RagService


# Jetons de test (>= 16 caractères). Le contexte est dérivé côté serveur de ces
# jetons ; il n'apparaît JAMAIS dans le corps des requêtes.
ALPHA_ALICE_TOKEN = "tok-alpha-alice-0123456789"
ALPHA_BOB_TOKEN = "tok-alpha-bob-0123456789ab"
BETA_CAROL_TOKEN = "tok-beta-carol-0123456789ab"

ALICE_CONTEXT = AuthorizationContext(
    tenant_id="alpha", user_id="alice", groups=("support",), clearance=1
)
BOB_CONTEXT = AuthorizationContext(
    tenant_id="alpha", user_id="bob", groups=("support",), clearance=1
)
CAROL_CONTEXT = AuthorizationContext(
    tenant_id="beta", user_id="carol", groups=("support",), clearance=9
)


def build_test_authenticator() -> TokenAuthenticator:
    return TokenAuthenticator.from_principals(
        {
            ALPHA_ALICE_TOKEN: ALICE_CONTEXT,
            ALPHA_BOB_TOKEN: BOB_CONTEXT,
            BETA_CAROL_TOKEN: CAROL_CONTEXT,
        }
    )


SHARED_AUTHENTICATOR = build_test_authenticator()


def request(
    app,
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    content_type: str = "application/json",
    host: str = "localhost:8080",
    token: str | None = ALPHA_ALICE_TOKEN,
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
    if token is not None:
        environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    captured: dict[str, Any] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    response_body = b"".join(app(environ, start_response))
    content_type = captured["headers"].get("Content-Type", "")
    data = json.loads(response_body) if "application/json" in content_type else response_body.decode("utf-8")
    return captured["status"], captured["headers"], data


def _document(**overrides: Any) -> dict[str, Any]:
    base = {
        "document_id": "guide",
        "content": "Hermes s'installe avec pipx install hermes-agent.",
        "visibility": "private",
        "allowed_groups": ["support"],
        "allowed_users": [],
        "classification": 1,
        "doc_version": 1,
        "source_uri": "local://guide",
    }
    base.update(overrides)
    return base


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = make_app(RagService(), authenticator=SHARED_AUTHENTICATOR)

    def test_import_then_question_over_http_returns_citation(self) -> None:
        import_status, _, imported = request(
            self.app,
            "POST",
            "/api/documents",
            {
                "document": _document(
                    document_id="guide-installation",
                    content="Pour installer Hermes, utilisez pipx install hermes-agent.",
                    source_uri="file:///docs/guide.md",
                )
            },
        )
        answer_status, _, answered = request(
            self.app,
            "POST",
            "/api/questions",
            {"question": "Comment installer Hermes ?"},
        )

        self.assertEqual(import_status, "201 Created")
        self.assertEqual(imported["document_id"], "guide-installation")
        self.assertEqual(answer_status, "200 OK")
        self.assertFalse(answered["abstained"])
        self.assertEqual(answered["citations"][0]["document_id"], "guide-installation")

    def test_missing_bearer_token_is_unauthorized(self) -> None:
        status, headers, response = request(
            self.app,
            "POST",
            "/api/questions",
            {"question": "Bonjour"},
            token=None,
        )
        self.assertEqual(status, "401 Unauthorized")
        self.assertEqual(response["error"], "unauthorized")
        self.assertEqual(headers.get("WWW-Authenticate"), "Bearer")
        # Aucun détail interne ne doit fuiter.
        self.assertNotIn("detail", response)

    def test_unknown_bearer_token_is_unauthorized(self) -> None:
        status, _, response = request(
            self.app,
            "POST",
            "/api/questions",
            {"question": "Bonjour"},
            token="tok-unknown-000000000000",
        )
        self.assertEqual(status, "401 Unauthorized")
        self.assertEqual(response["error"], "unauthorized")

    def test_client_cannot_spoof_tenant_or_owner_via_body(self) -> None:
        # Alice importe en tentant de se déclarer tenant 'beta' et owner 'mallory'
        # dans le corps : ces champs doivent être IGNORÉS, l'identité vient du jeton.
        status, _, imported = request(
            self.app,
            "POST",
            "/api/documents",
            {
                "document": _document(
                    document_id="spoof-guide",
                    tenant_id="beta",
                    owner_id="mallory",
                    source_uri="local://spoof",
                )
            },
            token=ALPHA_ALICE_TOKEN,
        )
        self.assertEqual(status, "201 Created")
        # Carol (tenant beta) ne doit PAS voir le document d'Alice (tenant alpha).
        # Preuve que le tenant du doc est bien 'alpha' (dérivé du jeton d'Alice),
        # pas 'beta' comme réclamé dans le corps.
        status, _, answered = request(
            self.app,
            "POST",
            "/api/questions",
            {"question": "Comment installer Hermes ?"},
            token=BETA_CAROL_TOKEN,
        )
        self.assertEqual(status, "200 OK")
        self.assertTrue(answered["abstained"])
        self.assertEqual(answered["citations"], [])

    def test_another_user_cannot_overwrite_existing_document_owner(self) -> None:
        request(
            self.app,
            "POST",
            "/api/documents",
            {"document": _document(document_id="owned", source_uri="local://owned")},
            token=ALPHA_ALICE_TOKEN,
        )
        status, _, response = request(
            self.app,
            "POST",
            "/api/documents",
            {
                "document": _document(
                    document_id="owned", doc_version=2, source_uri="local://owned-2"
                )
            },
            token=ALPHA_BOB_TOKEN,
        )
        self.assertEqual(status, "403 Forbidden")
        self.assertEqual(response["error"], "forbidden")
        self.assertNotIn("detail", response)

    def test_document_lock_contention_returns_503_without_leaking_details(self) -> None:
        from rag_hermes.qdrant_write_lock import DocumentWriteLockTimeout

        class ContendedService(RagService):
            def import_document(self, document, *, context):
                raise DocumentWriteLockTimeout("secret lock path /private/locks")

        app = make_app(ContendedService(), authenticator=SHARED_AUTHENTICATOR)
        status, headers, response = request(
            app, "POST", "/api/documents", {"document": _document()}
        )
        self.assertEqual(status, "503 Service Unavailable")
        self.assertEqual(response, {"error": "document_write_busy"})
        self.assertEqual(headers.get("Retry-After"), "1")

    def test_generator_failure_returns_bad_gateway_not_abstention(self) -> None:
        def fail_generator(question, evidence):
            raise GenerationError("provider unavailable")

        app = make_app(
            RagService(generator=fail_generator), authenticator=SHARED_AUTHENTICATOR
        )
        request(app, "POST", "/api/documents", {"document": _document()})

        status, _, response = request(
            app,
            "POST",
            "/api/questions",
            {"question": "Comment installer Hermes ?"},
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
        app = make_app(service, authenticator=SHARED_AUTHENTICATOR)
        for suffix in ("un", "deux"):
            request(
                app,
                "POST",
                "/api/documents",
                {
                    "document": _document(
                        document_id=f"guide-{suffix}",
                        content=f"Hermes s'installe avec la methode {suffix}.",
                        source_uri=f"local://guide-{suffix}",
                    )
                },
            )

        status, _, response = request(
            app,
            "POST",
            "/api/questions",
            {"question": "Comment installer Hermes ?"},
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
        app = make_app(
            RagService(generator=generator), authenticator=SHARED_AUTHENTICATOR
        )
        request(app, "POST", "/api/documents", {"document": _document()})

        status, _, response = request(
            app,
            "POST",
            "/api/questions",
            {"question": "Comment installer Hermes ?"},
        )

        self.assertEqual(status, "502 Bad Gateway")
        self.assertEqual(response, {"error": "generation_failed"})

    def test_generator_answer_without_resolved_citation_returns_bad_gateway(self) -> None:
        def generate(question, evidence):
            return "Réponse non fondée sans marqueur de source."

        app = make_app(
            RagService(generator=generate), authenticator=SHARED_AUTHENTICATOR
        )
        request(app, "POST", "/api/documents", {"document": _document()})

        status, _, response = request(
            app,
            "POST",
            "/api/questions",
            {"question": "Comment installer Hermes ?"},
        )

        self.assertEqual(status, "502 Bad Gateway")
        self.assertEqual(response, {"error": "generation_failed"})

    def test_home_page_exposes_mobile_import_and_question_interface(self) -> None:
        status, headers, html = request(self.app, "GET", "/", token=None)

        self.assertEqual(status, "200 OK")
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn('name="viewport"', html)
        self.assertIn('id="document-form"', html)
        self.assertIn('id="question-form"', html)
        self.assertIn('id="token"', html)

    def test_home_page_carries_strict_security_headers(self) -> None:
        _, headers, html = request(self.app, "GET", "/", token=None)
        # Anti-clickjacking, MIME sniffing, referrer leakage and a strict CSP.
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        csp = headers["Content-Security-Policy"]
        self.assertIn("default-src 'none'", csp)
        self.assertIn("script-src 'self'", csp)
        # The critical vector — scripts — must never allow inline execution.
        self.assertNotIn("script-src 'unsafe-inline'", csp)
        self.assertNotIn("'unsafe-eval'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        # The JS is externalised so the strict CSP is honoured: no inline <script> body.
        self.assertNotIn("addEventListener", html)
        self.assertIn('src="/app.js"', html)

    def test_app_js_is_served_as_javascript_with_security_headers(self) -> None:
        status, headers, body = request(self.app, "GET", "/app.js", token=None)
        self.assertEqual(status, "200 OK")
        self.assertIn("javascript", headers["Content-Type"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        # The externalised script holds the form logic.
        self.assertIn("addEventListener", body)
        self.assertIn("/api/questions", body)
        # L'UI envoie le jeton via l'en-tête Authorization (pas de contexte en corps).
        self.assertIn("Authorization", body)

    def test_app_js_rejects_non_get(self) -> None:
        status, headers, _ = request(self.app, "POST", "/app.js", token=None)
        self.assertEqual(status, "405 Method Not Allowed")
        self.assertEqual(headers.get("Allow"), "GET")

    def test_json_responses_carry_security_headers(self) -> None:
        # Even an error JSON response must carry the baseline security headers.
        status, headers, _ = request(self.app, "GET", "/does-not-exist", token=None)
        self.assertEqual(status, "404 Not Found")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")

    def test_mutating_route_rejects_non_json_content_type(self) -> None:
        status, _, response = request(
            self.app,
            "POST",
            "/api/questions",
            {"question": "Bonjour"},
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
            token=None,
        )

        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(response["error"], "invalid_host")

        ipv6_suffix_status, _, ipv6_suffix_response = request(
            self.app,
            "GET",
            "/",
            host="[::1]evil.example",
            token=None,
        )
        self.assertEqual(ipv6_suffix_status, "400 Bad Request")
        self.assertEqual(ipv6_suffix_response["error"], "invalid_host")

    def test_known_api_route_rejects_wrong_method_with_allow_header(self) -> None:
        status, headers, response = request(
            self.app, "GET", "/api/questions", token=None
        )

        self.assertEqual(status, "405 Method Not Allowed")
        self.assertEqual(headers["Allow"], "POST")
        self.assertEqual(response["error"], "method_not_allowed")

    def test_oversized_body_returns_payload_too_large(self) -> None:
        status, _, response = request(
            self.app,
            "POST",
            "/api/questions",
            {"question": "x" * 1_000_000},
        )

        self.assertEqual(status, "413 Payload Too Large")
        self.assertEqual(response["error"], "payload_too_large")

    def test_question_rejects_empty_question(self) -> None:
        status, _, response = request(
            self.app,
            "POST",
            "/api/questions",
            {"question": "   "},
        )
        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(response["error"], "invalid_request")

    def test_document_rejects_invalid_acl_types_and_empty_values(self) -> None:
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
                invalid_document = _document()
                invalid_document[field] = value
                status, _, response = request(
                    self.app,
                    "POST",
                    "/api/documents",
                    {"document": invalid_document},
                )
                self.assertEqual(status, "400 Bad Request")
                self.assertEqual(response["error"], "invalid_request")


class _RaisingService:
    """Service minimal qui échoue toujours, pour éprouver le mappage HTTP.

    L'application n'appelle que `answer` / `import_document` : un double fidèle
    suffit à provoquer l'erreur exacte à mapper, sans Qdrant ni générateur.
    """

    def __init__(self, error: BaseException) -> None:
        self._error = error

    def answer(self, question: str, *, context: AuthorizationContext) -> Any:
        raise self._error

    def import_document(self, document: Any, *, context: AuthorizationContext) -> Any:
        raise self._error


class ServerFailureMappingTests(unittest.TestCase):
    def _app(self, error: BaseException):
        return make_app(_RaisingService(error), authenticator=SHARED_AUTHENTICATOR)  # type: ignore[arg-type]

    def test_reranker_budget_exceeded_is_a_backend_error_not_a_bad_request(self) -> None:
        # `RerankerBudgetExceeded` hérite de ValueError : sans clause dédiée,
        # un dépassement de budget côté serveur est rendu « 400 invalid_request »
        # et accuse le client d'une faute qui n'est pas la sienne.
        app = self._app(
            RerankerBudgetExceeded("reranker pair has 731 tokens, exceeding max_length 512")
        )
        status, headers, response = request(
            app, "POST", "/api/questions", {"question": "Comment installer Hermes ?"}
        )
        self.assertEqual(status, "502 Bad Gateway")
        self.assertEqual(response, {"error": "backend_error"})
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        # Aucun détail interne (compte de tokens, budget) ne doit fuiter.
        self.assertNotIn("731", json.dumps(response))

    def test_unexpected_error_is_a_json_500_with_security_headers(self) -> None:
        # Une panne imprévue (ex. Qdrant injoignable) remontait jusqu'à wsgiref :
        # 500 HTML générique, SANS en-têtes de sécurité et avec le risque de
        # publier la trace. Elle doit devenir un 500 JSON muet et en-têté.
        app = self._app(RuntimeError("Qdrant unavailable at 10.0.0.5:6333"))
        status, headers, response = request(
            app, "POST", "/api/questions", {"question": "Comment installer Hermes ?"}
        )
        self.assertEqual(status, "500 Internal Server Error")
        self.assertEqual(response, {"error": "internal_error"})
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("Content-Security-Policy", headers)
        self.assertEqual(headers["Cache-Control"], "no-store")
        serialized = json.dumps(response)
        self.assertNotIn("Qdrant", serialized)
        self.assertNotIn("10.0.0.5", serialized)

    def test_unexpected_error_on_import_is_also_a_json_500(self) -> None:
        app = self._app(OSError("disk is gone"))
        status, _, response = request(
            app, "POST", "/api/documents", {"document": _document()}
        )
        self.assertEqual(status, "500 Internal Server Error")
        self.assertEqual(response, {"error": "internal_error"})

    def test_real_service_with_an_over_budget_reranker_returns_502(self) -> None:
        # Preuve sur le VRAI service (pas le double) : le budget du reranker est
        # franchi pendant `service.answer`, exactement le chemin que l'audit
        # voyait rendu en 400.
        def over_budget_reranker(question, chunks):
            raise RerankerBudgetExceeded(
                "reranker pair has 900 tokens, exceeding max_length 512"
            )

        service = RagService(reranker=over_budget_reranker, retrieval_k=5, top_k=1)
        app = make_app(service, authenticator=SHARED_AUTHENTICATOR)
        created, _, _ = request(
            app,
            "POST",
            "/api/documents",
            {
                "document": _document(
                    document_id="guide-budget",
                    content="Pour installer Hermes, utilisez pipx install hermes-agent.",
                )
            },
        )
        self.assertEqual(created, "201 Created")

        status, _, response = request(
            app, "POST", "/api/questions", {"question": "Comment installer Hermes ?"}
        )
        self.assertEqual(status, "502 Bad Gateway")
        self.assertEqual(response, {"error": "backend_error"})

    def test_keyboard_interrupt_is_not_swallowed_as_a_500(self) -> None:
        # Le filet de sécurité attrape `Exception`, jamais `BaseException` :
        # un arrêt du process ne doit pas être déguisé en réponse 500.
        app = self._app(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            request(app, "POST", "/api/questions", {"question": "Comment installer ?"})


if __name__ == "__main__":
    unittest.main()
