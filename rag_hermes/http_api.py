from __future__ import annotations

from dataclasses import asdict
import json
import re
from typing import Any, Callable, Iterable

from .acl import AuthorizationContext
from .ingestion import Document
from .service import RagService
from .web_ui import INDEX_HTML

_MAX_BODY_BYTES = 1_000_000
_TRUSTED_HOST_RE = re.compile(
    r"^(?:(?:localhost|127\.0\.0\.1)(?::\d{1,5})?|\[::1\](?::\d{1,5})?)$"
)


def _context(value: dict[str, Any]) -> AuthorizationContext:
    return AuthorizationContext(
        tenant_id=str(value["tenant_id"]),
        user_id=str(value["user_id"]),
        groups=tuple(str(group) for group in value.get("groups", [])),
        clearance=int(value["clearance"]),
    )


def _document(value: dict[str, Any]) -> Document:
    return Document(
        document_id=str(value["document_id"]),
        content=str(value["content"]),
        tenant_id=str(value["tenant_id"]),
        visibility=str(value["visibility"]),
        owner_id=str(value["owner_id"]),
        allowed_groups=tuple(str(group) for group in value.get("allowed_groups", [])),
        allowed_users=tuple(str(user) for user in value.get("allowed_users", [])),
        classification=int(value["classification"]),
        doc_version=int(value["doc_version"]),
        source_uri=str(value["source_uri"]),
        acl_version=int(value.get("acl_version", 1)),
    )


def _json_response(
    start_response: Callable[..., Any],
    status: str,
    value: dict[str, Any],
) -> Iterable[bytes]:
    body = json.dumps(value, ensure_ascii=False).encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
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
            ("X-Content-Type-Options", "nosniff"),
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
        if method != "POST" or path not in {"/api/documents", "/api/questions"}:
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
            if length < 1 or length > _MAX_BODY_BYTES:
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

            result = service.answer(str(payload["question"]), context=context)
            return _json_response(start_response, "200 OK", asdict(result))
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
