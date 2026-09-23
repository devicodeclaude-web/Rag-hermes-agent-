from __future__ import annotations

import hashlib
import math
import uuid
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


def chunk_to_point(chunk: Chunk, vector: list[float]) -> dict[str, Any]:
    if not vector:
        raise ValueError("vector cannot be empty")
    stable_key = f"{chunk.chunk_id}:{chunk.source_sha}:{chunk.doc_version}"
    point_id = str(uuid.uuid5(_POINT_NAMESPACE, stable_key))
    return {
        "id": point_id,
        "vector": {"dense": vector},
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
