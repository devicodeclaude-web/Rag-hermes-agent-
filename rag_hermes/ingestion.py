from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from .acl import Chunk


@dataclass(frozen=True)
class Document:
    document_id: str
    content: str
    tenant_id: str
    visibility: str
    owner_id: str
    allowed_groups: tuple[str, ...]
    allowed_users: tuple[str, ...]
    classification: int
    doc_version: int
    source_uri: str


def chunk_document(
    document: Document, *, max_tokens: int = 420, overlap_tokens: int = 40
) -> list[Chunk]:
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be between 0 and max_tokens - 1")

    words = document.content.split()
    if not words:
        return []

    source_sha = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
    step = max_tokens - overlap_tokens
    chunks: list[Chunk] = []
    for index, start in enumerate(range(0, len(words), step)):
        window = words[start : start + max_tokens]
        if not window:
            break
        chunk_id_material = (
            f"{document.document_id}:{document.doc_version}:{index}:{source_sha}"
        )
        chunk_id = hashlib.sha256(chunk_id_material.encode("utf-8")).hexdigest()[:24]
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                document_id=document.document_id,
                text=" ".join(window),
                tenant_id=document.tenant_id,
                visibility=document.visibility,
                allowed_groups=document.allowed_groups,
                allowed_users=document.allowed_users,
                owner_id=document.owner_id,
                classification=document.classification,
                doc_version=document.doc_version,
                source_sha=source_sha,
                source_uri=document.source_uri,
            )
        )
        if start + max_tokens >= len(words):
            break
    return chunks


def chunk_document_tokens(
    document: Document,
    tokenizer: Any,
    *,
    max_passage_tokens: int = 384,
    overlap_tokens: int = 64,
    tokenizer_name: str,
    tokenizer_revision: str,
) -> list[Chunk]:
    if max_passage_tokens < 1:
        raise ValueError("max_passage_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= max_passage_tokens:
        raise ValueError(
            "overlap_tokens must be between 0 and max_passage_tokens - 1"
        )
    if not tokenizer_name or not tokenizer_revision:
        raise ValueError("tokenizer name and revision are required")
    if not document.content:
        return []

    encoded = tokenizer(
        document.content,
        add_special_tokens=False,
        truncation=False,
        return_offsets_mapping=True,
    )
    input_ids = encoded["input_ids"]
    offsets = encoded["offset_mapping"]
    if len(input_ids) != len(offsets):
        raise ValueError("tokenizer input_ids and offset_mapping lengths differ")
    if not input_ids:
        return []

    content_hash = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
    step = max_passage_tokens - overlap_tokens
    chunks: list[Chunk] = []
    for index, token_start in enumerate(range(0, len(input_ids), step)):
        token_end = min(token_start + max_passage_tokens, len(input_ids))
        start_offset = int(offsets[token_start][0])
        end_offset = int(offsets[token_end - 1][1])
        text = document.content[start_offset:end_offset]
        chunk_id_material = (
            f"{document.document_id}:{document.doc_version}:{index}:"
            f"{start_offset}:{end_offset}:{content_hash}:"
            f"{tokenizer_name}@{tokenizer_revision}"
        )
        chunk_id = hashlib.sha256(chunk_id_material.encode("utf-8")).hexdigest()[:24]
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                document_id=document.document_id,
                text=text,
                tenant_id=document.tenant_id,
                visibility=document.visibility,
                allowed_groups=document.allowed_groups,
                allowed_users=document.allowed_users,
                owner_id=document.owner_id,
                classification=document.classification,
                doc_version=document.doc_version,
                source_sha=content_hash,
                source_uri=document.source_uri,
                section="",
                start_offset=start_offset,
                end_offset=end_offset,
                token_count=token_end - token_start,
                tokenizer_name=tokenizer_name,
                tokenizer_revision=tokenizer_revision,
                content_hash=content_hash,
            )
        )
        if token_end >= len(input_ids):
            break
    return chunks
