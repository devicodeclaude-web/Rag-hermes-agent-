from __future__ import annotations

from dataclasses import asdict
import json
import re
from typing import Any, Callable, Iterable

from .acl import AuthorizationContext
from .generator import GenerationError
from .ingestion import Document
from .service import RagService
from .web_ui import APP_JS, INDEX_HTML

_MAX_BODY_BYTES = 1_000_000
_TRUSTED_HOST_RE = re.compile(
    r"^(?:(?:localhost|127\.0\.0\.1)(?::\d{1,5})?|\[::1\](?::\d{1,5})?)$"
)

# A strict Content-Security-Policy is only possible because the UI JavaScript is
# served from /app.js (no inline <script>): script-src 'self' with no
# 'unsafe-inline'. default-src 'none' denies everything not explicitly allowed.
_CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'unsafe-inline'; "
    "connect-src 'self'; "
    "img-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)
# Baseline security headers applied to EVERY response (HTML, JS and JSON).
_SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Content-Security-Policy", _CSP),
)


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    return value


def _string(value: Any, field: str, *, preserve: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value if preserve else value.strip()


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a JSON array")
    return tuple(_string(item, field) for item in value)


def _context(raw: Any) -> AuthorizationContext:
    value = _object(raw, "context")
    return AuthorizationContext(
        tenant_id=_string(value["tenant_id"], "context.tenant_id"),
        user_id=_string(value["user_id"], "context.user_id"),
        groups=_string_list(value.get("groups", []), "context.groups"),
        clearance=_integer(value["clearance"], "context.clearance"),
    )


def _document(raw: Any) -> Document:
    value = _object(raw, "document")
    visibility = _string(value["visibility"], "document.visibility")
    if visibility not in {"public", "private"}:
        raise ValueError("document.visibility must be public or private")
    return Document(
        document_id=_string(value["document_id"], "document.document_id"),
        content=_string(value["content"], "document.content", preserve=True),
        tenant_id=_string(value["tenant_id"], "document.tenant_id"),
        visibility=visibility,
        owner_id=_string(value["owner_id"], "document.owner_id"),
        allowed_groups=_string_list(
            value.get("allowed_groups", []), "document.allowed_groups"
        ),
        allowed_users=_string_list(
            value.get("allowed_users", []), "document.allowed_users"
        ),
        classification=_integer(
            value["classification"], "document.classification"
        ),
        doc_version=_integer(value["doc_version"], "document.doc_version", minimum=1),
        source_uri=_string(value["source_uri"], "document.source_uri"),
        acl_version=_integer(
            value.get("acl_version", 1), "document.acl_version", minimum=1
        ),
    )


def _json_response(
    start_response: Callable[..., Any],
    status: str,
    value: dict[str, Any],
    *,
    extra_headers: tuple[tuple[str, str], ...] = (),
) -> Iterable[bytes]:
    body = json.dumps(value, ensure_ascii=False).encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            *_SECURITY_HEADERS,
            *extra_headers,
        ],
    )
    return [body]


def _html_response(start_response: Callable[..., Any]) -> Iterable[bytes]:
    body = INDEX_HTML.encode("utf-8")
    start_response(
        "200 OK",
        [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            *_SECURITY_HEADERS,
        ],
    )
    return [body]


def _javascript_response(start_response: Callable[..., Any]) -> Iterable[bytes]:
    body = APP_JS.encode("utf-8")
    start_response(
        "200 OK",
        [
            ("Content-Type", "text/javascript; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            *_SECURITY_HEADERS,
        ],
    )
    return [body]


def make_app(service: RagService):
    def app(environ: dict[str, Any], start_response: Callable[..., Any]):
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        host_header = str(environ.get("HTTP_HOST", "")).strip().lower()
        if not _TRUSTED_HOST_RE.fullmatch(host_header):
            return _json_response(
                start_response,
                "400 Bad Request",
                {"error": "invalid_host"},
            )
        if method == "GET" and path == "/":
            return _html_response(start_response)
        if path == "/app.js":
            if method != "GET":
                return _json_response(
                    start_response,
                    "405 Method Not Allowed",
                    {"error": "method_not_allowed"},
                    extra_headers=(("Allow", "GET"),),
                )
            return _javascript_response(start_response)
        api_paths = {"/api/documents", "/api/questions"}
        if path in api_paths and method != "POST":
            return _json_response(
                start_response,
                "405 Method Not Allowed",
                {"error": "method_not_allowed"},
                extra_headers=(("Allow", "POST"),),
            )
        if path not in api_paths:
            return _json_response(start_response, "404 Not Found", {"error": "not_found"})
        content_type = str(environ.get("CONTENT_TYPE", "")).split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return _json_response(
                start_response,
                "415 Unsupported Media Type",
                {"error": "unsupported_media_type"},
            )

        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
            if length > _MAX_BODY_BYTES:
                return _json_response(
                    start_response,
                    "413 Payload Too Large",
                    {"error": "payload_too_large"},
                )
            if length < 1:
                raise ValueError("request body size is invalid")
            raw = environ["wsgi.input"].read(length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            context = _context(payload["context"])

            if path == "/api/documents":
                result = service.import_document(
                    _document(payload["document"]),
                    context=context,
                )
                return _json_response(start_response, "201 Created", asdict(result))

            question = _string(payload["question"], "question")
            result = service.answer(question, context=context)
            return _json_response(start_response, "200 OK", asdict(result))
        except GenerationError:
            return _json_response(
                start_response,
                "502 Bad Gateway",
                {"error": "generation_failed"},
            )
        except PermissionError as exc:
            return _json_response(
                start_response,
                "403 Forbidden",
                {"error": "forbidden", "detail": str(exc)},
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return _json_response(
                start_response,
                "400 Bad Request",
                {"error": "invalid_request", "detail": str(exc)},
            )

    return app
