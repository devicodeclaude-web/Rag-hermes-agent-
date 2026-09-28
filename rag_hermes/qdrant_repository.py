from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .acl import AuthorizationContext, Chunk, filter_authorized
from .ingestion import Document
from .qdrant_filter import build_qdrant_filter
from .qdrant_store import chunk_to_point
from .retrieval import SearchResult


@dataclass(frozen=True)
class QdrantReplaceResult:
    document_id: str
    chunk_count: int


class QdrantChunkRepository:
    """Persist chunks in Qdrant without choosing an embedding model."""

    def __init__(
        self,
        client: Any,
        *,
        collection: str,
        embed: Callable[[str], list[float]],
    ) -> None:
        if not collection.strip():
            raise ValueError("collection is required")
        self._client = client
        self._collection = collection
        self._embed = embed

    def replace_document(
        self,
        document: Document,
        chunks: Iterable[Chunk],
    ) -> QdrantReplaceResult:
        materialized = list(chunks)
        points = [
            chunk_to_point(chunk, self._embed(chunk.text))
            for chunk in materialized
        ]
        new_point_ids = [point["id"] for point in points]
        if points:
            # Upsert the new revision first so a failure never leaves the
            # document deleted (compensating write, not a silent gap).
            self._client.upsert(self._collection, points)
        # Delete every stale point of this (tenant, document) that is not part
        # of the revision we just wrote.
        query_filter: dict[str, Any] = {
            "must": [
                {"key": "tenant_id", "match": {"value": document.tenant_id}},
                {"key": "document_id", "match": {"value": document.document_id}},
            ]
        }
        if new_point_ids:
            query_filter["must_not"] = [{"has_id": new_point_ids}]
        self._client.delete_points(self._collection, query_filter)
        return QdrantReplaceResult(document.document_id, len(materialized))

    @staticmethod
    def _chunk_from_point(point: dict[str, Any]) -> Chunk:
        payload = point.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Qdrant candidate payload is required")
        try:
            return Chunk(
                chunk_id=str(payload["chunk_id"]),
                document_id=str(payload["document_id"]),
                text=str(payload["text"]),
                tenant_id=str(payload["tenant_id"]),
                visibility=str(payload["visibility"]),
                allowed_groups=tuple(payload.get("allowed_group_ids", [])),
                allowed_users=tuple(payload.get("allowed_user_ids", [])),
                owner_id=str(payload["owner_id"]),
                classification=int(payload["classification"]),
                doc_version=int(payload["doc_version"]),
                source_sha=str(payload["source_sha"]),
                source_uri=str(payload.get("source_uri", "")),
                section=str(payload.get("section", "")),
                start_offset=int(payload.get("start_offset", 0)),
                end_offset=int(payload.get("end_offset", 0)),
                token_count=int(payload.get("token_count", 0)),
                tokenizer_name=str(payload.get("tokenizer_name", "")),
                tokenizer_revision=str(payload.get("tokenizer_revision", "")),
                content_hash=str(payload.get("content_hash", "")),
                acl_version=int(payload.get("acl_version", 1)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid Qdrant candidate payload: {exc}") from exc

    def search(
        self,
        query: str,
        *,
        context: AuthorizationContext,
        limit: int = 10,
    ) -> list[SearchResult]:
        if limit < 1:
            raise ValueError("limit must be positive")
        vector = self._embed(query)
        candidates = self._client.query(
            self._collection,
            vector,
            query_filter=build_qdrant_filter(context),
            limit=limit,
        )
        results: list[SearchResult] = []
        for point in candidates:
            chunk = self._chunk_from_point(point)
            if not filter_authorized([chunk], context):
                continue
            results.append(SearchResult(chunk=chunk, score=float(point.get("score", 0.0))))
        return results
