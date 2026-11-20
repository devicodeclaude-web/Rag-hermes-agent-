"""Qdrant service identities: mint and validate collection-scoped JWTs.

SEC-03. The V1 service must hold two credentials that the SERVER can tell
apart: a read-only identity for retrieval and a points-read-write identity for
document replacement. Checking that two environment variables merely differ is
not enough — an operator can paste the admin key into both. So the tokens are
parsed here and refused unless their `access` claim is exactly the expected
collection-scoped capability.

The signature is NOT verified here (only Qdrant knows the signing key); this
module constrains what the service is willing to CARRY, and Qdrant remains the
authority that enforces it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

QUERY_ACCESS = "r"
WRITE_ACCESS = "prw"
_MINTABLE = (QUERY_ACCESS, WRITE_ACCESS)


class _TokenError(ValueError):
    """Internal: carries a reason that never includes the token itself."""


def _b64url_decode(segment: str) -> bytes:
    if not segment or any(
        char not in
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for char in segment
    ):
        raise _TokenError("is not a base64url JWT segment")
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (ValueError, TypeError):
        raise _TokenError("is not a base64url JWT segment") from None


def _payload(token: str) -> dict[str, Any]:
    if type(token) is not str or not token:
        raise _TokenError("is empty")
    segments = token.split(".")
    if len(segments) != 3 or not all(segments):
        raise _TokenError("is not a three-part JWT")
    try:
        payload = json.loads(_b64url_decode(segments[1]))
    except json.JSONDecodeError:
        raise _TokenError("has an unreadable JWT payload") from None
    if type(payload) is not dict:
        raise _TokenError("has an unreadable JWT payload")
    return payload


def collection_access_claims(token: str) -> tuple[tuple[str, str], ...]:
    """Return the ((collection, mode), ...) granted by a Qdrant JWT.

    A token without an `access` claim is a MANAGE token for Qdrant, so the
    absent claim is reported as such instead of being treated as empty.
    """
    payload = _payload(token)
    if "access" not in payload:
        raise _TokenError("has no access claim, which Qdrant reads as manage access")
    access = payload["access"]
    if type(access) is str:
        raise _TokenError(f"grants global {access!r} access instead of one collection")
    if type(access) is not list or not access:
        raise _TokenError("has a malformed access claim")
    claims: list[tuple[str, str]] = []
    for entry in access:
        if (type(entry) is not dict
                or type(entry.get("collection")) is not str or not entry["collection"]
                or type(entry.get("access")) is not str or not entry["access"]):
            raise _TokenError("has a malformed access claim")
        claims.append((entry["collection"], entry["access"]))
    return tuple(claims)


def _expiry(token: str) -> int | None:
    expiry = _payload(token).get("exp")
    if expiry is None:
        return None
    if type(expiry) is not int or type(expiry) is bool:
        raise _TokenError("has a malformed exp claim")
    return expiry


def _check(token: str, *, collection: str, expected: str) -> None:
    claims = collection_access_claims(token)
    if claims != ((collection, expected),):
        raise _TokenError(
            f"must grant exactly {expected!r} access to collection {collection!r}"
        )
    expiry = _expiry(token)
    if expiry is not None and expiry <= time.time():
        raise _TokenError("has expired")


def mint_collection_token(
    secret: str, *, collection: str, access: str, ttl_seconds: int
) -> str:
    """Mint the HS256 JWT Qdrant expects, scoped to one collection.

    `secret` is the operator's `service.api_key`: it signs the token and must
    never be handed to the service itself.
    """
    if type(secret) is not str or not secret:
        raise ValueError("signing secret must not be empty")
    if type(collection) is not str or not collection.strip():
        raise ValueError("collection must not be empty")
    if access not in _MINTABLE:
        raise ValueError(f"access must be one of {_MINTABLE}")
    if type(ttl_seconds) is not int or type(ttl_seconds) is bool or ttl_seconds < 1:
        raise ValueError("ttl_seconds must be a positive integer")

    def encode(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    data = "{}.{}".format(
        encode({"alg": "HS256", "typ": "JWT"}),
        encode({
            "access": [{"collection": collection.strip(), "access": access}],
            "exp": int(time.time()) + ttl_seconds,
        }),
    )
    signature = hmac.new(
        secret.encode("utf-8"), data.encode("ascii"), hashlib.sha256
    ).digest()
    return data + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def validate_service_tokens(*, query_key: str, write_key: str, collection: str) -> None:
    """Refuse any service credential pair that is not least-privilege.

    Raises ValueError naming the offending environment variable. The token and
    its contents are never included in the message, so a misconfiguration can
    be logged safely.
    """
    if type(collection) is not str or not collection.strip():
        raise ValueError("RAG_QDRANT_COLLECTION must not be empty")
    collection = collection.strip()
    for variable, token, expected in (
        ("RAG_QDRANT_QUERY_API_KEY", query_key, QUERY_ACCESS),
        ("RAG_QDRANT_WRITE_API_KEY", write_key, WRITE_ACCESS),
    ):
        try:
            _check(token, collection=collection, expected=expected)
        except _TokenError as reason:
            raise ValueError(
                f"{variable} {reason.args[0]}: mint a collection-scoped Qdrant JWT "
                f"with scripts/mint_qdrant_jwt.py (access {expected!r})"
            ) from None
    if query_key == write_key:
        raise ValueError(
            "RAG_QDRANT_QUERY_API_KEY and RAG_QDRANT_WRITE_API_KEY must be distinct tokens"
        )


def validate_audit_tokens(*, audit_key: str, query_key: str, collection: str) -> None:
    """Refuse the G1 audit window's credentials unless they are two readers.

    The audited candidate window compares the index to a canonical manifest
    and then queries it; neither role writes. Two DISTINCT read-only tokens
    keep the audit trail separable from user traffic.

    Both empty means "unauthenticated Qdrant", which only a development or
    local-fixture instance may be: it is accepted so the window stays usable
    there, but a half-configured pair is refused.
    """
    if type(collection) is not str or not collection.strip():
        raise ValueError("one normalized Qdrant collection is required")
    collection = collection.strip()
    audit_key = audit_key.strip() if type(audit_key) is str else audit_key
    query_key = query_key.strip() if type(query_key) is str else query_key
    if audit_key == "" and query_key == "":
        return
    for variable, token in (
        ("RAG_QDRANT_G1_AUDIT_API_KEY", audit_key),
        ("RAG_QDRANT_G1_QUERY_API_KEY", query_key),
    ):
        if type(token) is not str or not token:
            raise ValueError(
                f"{variable} is missing: either both G1 credentials are set, or "
                "neither (unauthenticated Qdrant)"
            )
        try:
            _check(token, collection=collection, expected=QUERY_ACCESS)
        except _TokenError as reason:
            raise ValueError(
                f"{variable} {reason.args[0]}: mint a read-only collection-scoped "
                f"Qdrant JWT with scripts/mint_qdrant_jwt.py --only {QUERY_ACCESS}"
            ) from None
    if audit_key == query_key:
        raise ValueError(
            "RAG_QDRANT_G1_AUDIT_API_KEY and RAG_QDRANT_G1_QUERY_API_KEY must be "
            "distinct tokens, so audit reads stay separable from query reads"
        )
