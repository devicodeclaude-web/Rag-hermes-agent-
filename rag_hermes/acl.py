from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AuthorizationContext:
    tenant_id: str
    user_id: str
    groups: tuple[str, ...]
    clearance: int


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    tenant_id: str
    visibility: str
    allowed_groups: tuple[str, ...]
    allowed_users: tuple[str, ...]
    owner_id: str
    classification: int
    doc_version: int
    source_sha: str
    source_uri: str = ""
    section: str = ""
    start_offset: int = 0
    end_offset: int = 0
    token_count: int = 0
    tokenizer_name: str = ""
    tokenizer_revision: str = ""
    content_hash: str = ""
    acl_version: int = 1

    def __post_init__(self) -> None:
        if self.visibility not in {"public", "private"}:
            raise ValueError("visibility must be public or private")
        if self.doc_version < 1:
            raise ValueError("doc_version must be positive")
        if self.classification < 0:
            raise ValueError("classification must be non-negative")
        if self.acl_version < 1:
            raise ValueError("acl_version must be positive")
        if not _SHA256_RE.fullmatch(self.source_sha):
            raise ValueError("source_sha must be a lowercase SHA-256 hex digest")


def _is_authorized(chunk: Chunk, context: AuthorizationContext) -> bool:
    is_global_public = chunk.tenant_id == "public" and chunk.visibility == "public"
    if chunk.tenant_id != context.tenant_id and not is_global_public:
        return False
    if chunk.classification > context.clearance:
        return False
    if chunk.visibility == "public":
        return True
    if chunk.owner_id == context.user_id or context.user_id in chunk.allowed_users:
        return True
    return bool(set(chunk.allowed_groups).intersection(context.groups))


def filter_authorized(
    chunks: Iterable[Chunk], context: AuthorizationContext | None
) -> list[Chunk]:
    if context is None:
        raise ValueError("authorization context is required")
    return [chunk for chunk in chunks if _is_authorized(chunk, context)]
