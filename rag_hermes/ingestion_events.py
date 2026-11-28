"""Read-only schema and replay for future ingestion evidence in canonical JSONL.

These locally stored events are NOT an independent operator generation receipt,
proof of a past Qdrant write, or permission to repair an index. No writer exists.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from .ingestion import Document
from .qdrant_rest import _validate_qdrant_endpoint
from .qdrant_store import stable_point_id

_EVENT_IDENTITY = frozenset({
    "event_version", "kind", "document_id", "tenant_id", "owner_id",
    "doc_version", "acl_version", "document_record_index", "document_line_sha256",
})
_INTENT_KEYS = _EVENT_IDENTITY | {"profile", "generation", "points"}
_CONFIRM_KEYS = _EVENT_IDENTITY | {"intent_record_index", "intent_line_sha256"}
_PROFILE_KEYS = frozenset({
    "repo_id", "revision", "tokenizer_sha256", "tokenizers_version",
    "max_passage_tokens", "overlap_tokens",
})
_GENERATION_KEYS = frozenset({
    "qdrant_origin", "collection", "generation_uuid", "operator_receipt_sha256",
})
_PAYLOAD_TEXT = frozenset({
    "chunk_id", "document_id", "text", "tenant_id", "visibility", "owner_id",
    "source_sha", "source_uri", "section", "tokenizer_name", "tokenizer_revision",
    "content_hash",
})
_PAYLOAD_LIST = frozenset({"allowed_group_ids", "allowed_user_ids"})
_PAYLOAD_INT = frozenset({
    "classification", "doc_version", "acl_version", "start_offset", "end_offset", "token_count",
})
_PAYLOAD_KEYS = _PAYLOAD_TEXT | _PAYLOAD_LIST | _PAYLOAD_INT | {"tombstone"}


def _hex(value: object, length: int) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value) is not None


def _nonempty(value: object) -> bool:
    return type(value) is str and bool(value) and not any(
        ord(c) < 32 or 127 <= ord(c) <= 159 for c in value
    )


def _exact_int(value: object, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _validate_points(points: object, document: Document, profile: dict[str, Any]) -> None:
    if type(points) is not list or not points:
        raise ValueError("ingestion intent needs a nonempty points array")
    seen: set[str] = set()
    content_hash = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
    for point in points:
        if type(point) is not dict or set(point) != {"id", "payload"}:
            raise ValueError("ingestion point keys must be exact")
        point_id, payload = point["id"], point["payload"]
        if type(payload) is not dict or set(payload) != _PAYLOAD_KEYS:
            raise ValueError("ingestion point payload keys must be exact")
        if any(type(payload[key]) is not str for key in _PAYLOAD_TEXT):
            raise ValueError("ingestion point payload text must be exact strings")
        if any(type(payload[key]) is not list or any(type(item) is not str for item in payload[key])
               for key in _PAYLOAD_LIST):
            raise ValueError("ingestion point payload ACL lists must be exact strings")
        if any(not _exact_int(payload[key]) for key in _PAYLOAD_INT):
            raise ValueError("ingestion point payload integers must be exact nonnegative ints")
        if payload["tombstone"] is not False:
            raise ValueError("ingestion intent cannot attest a tombstoned point")
        expected = {
            "document_id": document.document_id, "tenant_id": document.tenant_id,
            "owner_id": document.owner_id, "visibility": document.visibility,
            "allowed_group_ids": list(document.allowed_groups),
            "allowed_user_ids": list(document.allowed_users),
            "classification": document.classification, "doc_version": document.doc_version,
            "acl_version": document.acl_version, "source_sha": content_hash,
            "source_uri": document.source_uri, "content_hash": content_hash,
            "section": "", "tokenizer_name": profile["repo_id"],
            "tokenizer_revision": profile["revision"],
        }
        if any(payload[key] != value for key, value in expected.items()):
            raise ValueError("ingestion point differs from its canonical revision")
        start, end = payload["start_offset"], payload["end_offset"]
        if not (start < end <= len(document.content)) or payload["text"] != document.content[start:end]:
            raise ValueError("ingestion point text/offsets differ from canonical content")
        if not 1 <= payload["token_count"] <= profile["max_passage_tokens"]:
            raise ValueError("ingestion point token count is outside its profile")
        # The chunker hashes the token WINDOW index, not the index of emitted
        # points. Zero-width windows may be skipped, so reconstructing that
        # index from enumerate(points) rejects valid original chunks. Shape
        # checks here are NOT a completeness proof: the future ingestion writer
        # must compare this entire list with its freshly generated chunks, and
        # the repair preflight must compare a complete Qdrant scan before write.
        chunk_id = payload["chunk_id"]
        if not _hex(chunk_id, 24):
            raise ValueError("ingestion point chunk identity is invalid")
        expected_id = stable_point_id(
            tenant_id=document.tenant_id, document_id=document.document_id,
            chunk_id=chunk_id, source_sha=content_hash, doc_version=document.doc_version,
        )
        if type(point_id) is not str or point_id != expected_id or point_id in seen:
            raise ValueError("ingestion point id is wrong or duplicated")
        seen.add(point_id)


def validate_event(event: Any, *, document: Document, document_index: int,
                   document_digest: str) -> str:
    """Validate exact JSON structure and bind an event to the ORIGINAL line."""
    if type(event) is not dict or event.get("kind") not in ("ingestion_intent", "ingestion_confirmed"):
        raise ValueError("unknown canonical ingestion event")
    kind = event["kind"]
    if set(event) != (_INTENT_KEYS if kind == "ingestion_intent" else _CONFIRM_KEYS):
        raise ValueError("canonical ingestion event keys must match its kind exactly")
    if type(event["event_version"]) is not int or event["event_version"] != 1:
        raise ValueError("unsupported canonical ingestion event version")
    expected = {
        "document_id": document.document_id, "tenant_id": document.tenant_id,
        "owner_id": document.owner_id, "doc_version": document.doc_version,
        "acl_version": document.acl_version, "document_record_index": document_index,
        "document_line_sha256": document_digest,
    }
    if any(type(event[key]) is not type(value) or event[key] != value
           for key, value in expected.items()):
        raise ValueError("canonical ingestion event does not bind its document line")
    if kind == "ingestion_confirmed":
        if not _exact_int(event["intent_record_index"], 1) or not _hex(event["intent_line_sha256"], 64):
            raise ValueError("canonical confirmation intent reference is invalid")
        return kind
    if document.state != "active":
        raise ValueError("inactive canonical document cannot declare ingestion intent")
    profile = event["profile"]
    if type(profile) is not dict or set(profile) != _PROFILE_KEYS:
        raise ValueError("canonical ingestion profile keys must be exact")
    if (not _nonempty(profile["repo_id"]) or not _hex(profile["revision"], 40)
            or not _hex(profile["tokenizer_sha256"], 64)
            or not _nonempty(profile["tokenizers_version"])
            or not _exact_int(profile["max_passage_tokens"], 1)
            or not _exact_int(profile["overlap_tokens"])
            or profile["overlap_tokens"] >= profile["max_passage_tokens"]):
        raise ValueError("canonical ingestion profile is invalid")
    generation = event["generation"]
    if type(generation) is not dict or set(generation) != _GENERATION_KEYS:
        raise ValueError("canonical ingestion generation keys must be exact")
    origin = generation["qdrant_origin"]
    if not _nonempty(origin):
        raise ValueError("canonical ingestion origin is invalid")
    try:
        # Match the actual Qdrant transport policy: HTTPS or explicit local
        # loopback HTTP, without URL credentials, controls or normalization.
        valid_origin = _validate_qdrant_endpoint(origin, "") == origin
    except ValueError:
        valid_origin = False
    if (not valid_origin
            or not _nonempty(generation["collection"])
            or not _hex(generation["operator_receipt_sha256"], 64)):
        raise ValueError("canonical ingestion generation is invalid")
    try:
        generation_id = uuid.UUID(generation["generation_uuid"])
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("canonical ingestion generation UUID is invalid") from exc
    if generation_id.version != 4 or str(generation_id) != generation["generation_uuid"]:
        raise ValueError("canonical ingestion generation UUID must be canonical v4")
    _validate_points(event["points"], document, profile)
    return kind
