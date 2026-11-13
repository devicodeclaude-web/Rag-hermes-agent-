from __future__ import annotations

import hashlib
import math
import struct
import uuid
from collections.abc import Mapping
from numbers import Real
from typing import Any

from .acl import Chunk

_POINT_NAMESPACE = uuid.UUID("f27f8ba0-5ff1-4dc6-aa40-1b5543de9518")


def deterministic_test_vector(text: str, *, dimensions: int = 8) -> list[float]:
    """Generate a repeatable test vector. This is not an embedding model."""
    if dimensions < 1 or dimensions > 32:
        raise ValueError("dimensions must be between 1 and 32")
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [(digest[index] / 127.5) - 1.0 for index in range(dimensions)]
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        values[0] = 1.0
        norm = 1.0
    return [value / norm for value in values]


def lexical_weights_to_sparse_vector(weights: object) -> dict[str, list[int] | list[float]]:
    """Convert BGE-M3 decimal token-id weights into a nonempty sparse vector."""
    if not isinstance(weights, Mapping) or not weights:
        raise ValueError("sparse weights must be a nonempty mapping")
    pairs: list[tuple[int, float]] = []
    seen: set[int] = set()
    for key, value in weights.items():
        if (type(key) is not str or not key.isascii() or not key.isdecimal()
            or str(int(key)) != key or int(key) >= 2**32):
            raise ValueError("sparse token id must be a canonical uint32 decimal string")
        token_id = int(key)
        if token_id in seen:
            raise ValueError("sparse token id is duplicated")
        seen.add(token_id)
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("sparse weight must be a positive real number")
        try:
            weight = float(value)
            rounded = struct.unpack("f", struct.pack("f", weight))[0]
        except (OverflowError, ValueError) as exc:
            raise ValueError("sparse weight is outside float32 range") from exc
        if not math.isfinite(weight) or rounded <= 0.0 or not math.isfinite(rounded):
            raise ValueError("sparse weight must be finite and positive in float32")
        pairs.append((token_id, weight))
    if not pairs:
        raise ValueError("sparse weights must contain at least one entry")
    pairs.sort()
    return {"indices": [key for key, _ in pairs], "values": [value for _, value in pairs]}


def stable_point_id(
    *,
    tenant_id: str,
    document_id: str,
    chunk_id: str,
    source_sha: str,
    doc_version: int,
) -> str:
    """Derive the point ID from the full chunk identity.

    The tenant and the document belong in the key: without them two tenants
    ingesting the same document_id at the same version derive the SAME point ID
    (chunk_id is itself a hash of document_id/doc_version/index/source_sha), so
    the second upsert silently erases the first tenant's passages.

    Each part is length-prefixed, so the encoding is injective: a plain
    separator would move the boundary between two fields as soon as a field
    contained the separator itself (document_id comes from the client), which
    brings the silent overwrite straight back.
    """
    # Stay a total serializer (callers pass odd types on purpose to exercise
    # the read-side barriers), hence str() rather than a type check here; the
    # repository type-checks the identity before it ever writes.
    parts = (tenant_id, document_id, chunk_id, source_sha, doc_version)
    stable_key = "".join(f"{len(str(part))}\x1f{part}\x1f" for part in parts)
    return str(uuid.uuid5(_POINT_NAMESPACE, stable_key))


def chunk_to_point(
    chunk: Chunk, vector: list[float], *, sparse_weights: object | None = None
) -> dict[str, Any]:
    if type(vector) not in (list, tuple) or not vector:
        # Be explicit: an ndarray reaches `not vector` as an ambiguous truth
        # test, which surfaced as an unreadable error instead of a refusal.
        raise ValueError("vector must be a nonempty list or tuple of numbers")
    vectors: dict[str, Any] = {"dense": vector}
    if sparse_weights is not None:
        vectors["sparse"] = lexical_weights_to_sparse_vector(sparse_weights)
    point_id = stable_point_id(
        tenant_id=chunk.tenant_id,
        document_id=chunk.document_id,
        chunk_id=chunk.chunk_id,
        source_sha=chunk.source_sha,
        doc_version=chunk.doc_version,
    )
    return {
        "id": point_id,
        "vector": vectors,
        "payload": {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "text": chunk.text,
            "tenant_id": chunk.tenant_id,
            "visibility": chunk.visibility,
            "allowed_group_ids": list(chunk.allowed_groups),
            "allowed_user_ids": list(chunk.allowed_users),
            "owner_id": chunk.owner_id,
            "classification": chunk.classification,
            "doc_version": chunk.doc_version,
            "acl_version": chunk.acl_version,
            "source_sha": chunk.source_sha,
            "source_uri": chunk.source_uri,
            "section": chunk.section,
            "start_offset": chunk.start_offset,
            "end_offset": chunk.end_offset,
            "token_count": chunk.token_count,
            "tokenizer_name": chunk.tokenizer_name,
            "tokenizer_revision": chunk.tokenizer_revision,
            "content_hash": chunk.content_hash or chunk.source_sha,
            "tombstone": False,
        },
    }
