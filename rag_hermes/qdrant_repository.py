from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Callable, Iterable

from .acl import AuthorizationContext, Chunk, filter_authorized
from .ingestion import Document
from .qdrant_filter import build_qdrant_filter
from .qdrant_preflight import verify_collection_ready
from .qdrant_store import chunk_to_point
from .retrieval import SearchResult


_OWNER_SCAN_LIMIT = 10_000

_MAX_SPARSE_TOKEN_ID = 2**32

_PAYLOAD_STR_FIELDS = (
    "chunk_id",
    "document_id",
    "text",
    "tenant_id",
    "visibility",
    "owner_id",
    "source_sha",
    "source_uri",
    "section",
    "tokenizer_name",
    "tokenizer_revision",
    "content_hash",
)

_PAYLOAD_INT_FIELDS = (
    "classification",
    "doc_version",
    "acl_version",
    "start_offset",
    "end_offset",
    "token_count",
)

_PAYLOAD_LIST_FIELDS = ("allowed_group_ids", "allowed_user_ids")

_PAYLOAD_FIELDS = frozenset(
    _PAYLOAD_STR_FIELDS + _PAYLOAD_INT_FIELDS + _PAYLOAD_LIST_FIELDS + ("tombstone",)
)

_CHUNK_STR_FIELDS = _PAYLOAD_STR_FIELDS
_CHUNK_INT_FIELDS = _PAYLOAD_INT_FIELDS


def _canonical_identifiers(value: object, field: str) -> tuple[str, ...]:
    """Snapshot an ACL identifier list as plain, immutable strings.

    Plain strings matter: a str subclass that overrides __eq__/__ne__ compares
    equal to the document while serializing a different identifier, and a
    mutable list could still be appended to after validation.
    """
    if type(value) not in (tuple, list):
        raise ValueError(f"{field} must be a tuple or list of strings")
    identifiers = tuple(value)
    if any(type(item) is not str for item in identifiers):
        raise ValueError(f"{field} must contain plain strings only")
    return identifiers


@dataclass(frozen=True)
class _DocumentSnapshot:
    """Frozen copy of the ACL/provenance facts a document claims."""

    document_id: str
    tenant_id: str
    owner_id: str
    visibility: str
    allowed_groups: tuple[str, ...]
    allowed_users: tuple[str, ...]
    classification: int
    doc_version: int
    acl_version: int
    source_uri: str
    content: str
    source_sha: str


def _snapshot_document(document: Document) -> _DocumentSnapshot:
    for field in (
        "document_id",
        "tenant_id",
        "owner_id",
        "visibility",
        "source_uri",
        "content",
    ):
        if type(getattr(document, field)) is not str:
            raise ValueError(f"document field {field!r} must be a plain string")
    for field in ("classification", "doc_version", "acl_version"):
        if type(getattr(document, field)) is not int:
            raise ValueError(f"document field {field!r} must be a plain integer")
    try:
        source_sha = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise ValueError("document content is not encodable as UTF-8") from exc
    return _DocumentSnapshot(
        document_id=document.document_id,
        tenant_id=document.tenant_id,
        owner_id=document.owner_id,
        visibility=document.visibility,
        allowed_groups=_canonical_identifiers(
            document.allowed_groups, "document allowed_groups"
        ),
        allowed_users=_canonical_identifiers(
            document.allowed_users, "document allowed_users"
        ),
        classification=document.classification,
        doc_version=document.doc_version,
        acl_version=document.acl_version,
        source_uri=document.source_uri,
        content=document.content,
        source_sha=source_sha,
    )


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
        embed_hybrid: Callable[[str], tuple[list[float], object]] | None = None,
    ) -> None:
        if not collection.strip():
            raise ValueError("collection is required")
        if embed_hybrid is not None and not callable(embed_hybrid):
            raise ValueError("embed_hybrid must be callable")
        self._client = client
        # Strip once: the preflight normalizes the name, so keeping the padded
        # value would verify one collection and write to another.
        self._collection = collection.strip()
        self._embed = embed
        self._embed_hybrid = embed_hybrid
        self._vector_size: int | None = None
        if embed_hybrid is not None:
            schema = verify_collection_ready(
                client, self._collection, require_sparse=True
            )
            self._vector_size = schema["vector_size"]

    def _assert_document_owner(self, document: Document) -> None:
        existing = self._client.scroll(
            self._collection,
            query_filter={
                "must": [
                    {"key": "tenant_id", "match": {"value": document.tenant_id}},
                    {
                        "key": "document_id",
                        "match": {"value": document.document_id},
                    },
                ],
            },
            limit=_OWNER_SCAN_LIMIT,
        )
        if len(existing) >= _OWNER_SCAN_LIMIT:
            raise PermissionError("document owner cannot be verified safely")
        for point in existing:
            payload = point.get("payload") if isinstance(point, dict) else None
            if not isinstance(payload, dict):
                raise PermissionError("document owner payload is invalid")
            if (
                payload.get("tenant_id") != document.tenant_id
                or payload.get("document_id") != document.document_id
                or not isinstance(payload.get("owner_id"), str)
                or payload["owner_id"] != document.owner_id
            ):
                raise PermissionError("only the existing document owner can replace it")

    def _assert_chunk_matches_document(
        self,
        snapshot: _DocumentSnapshot,
        chunk: Chunk,
    ) -> None:
        """Refuse any chunk whose ACL/provenance disagrees with its document.

        The ingestion caller supplies the chunks, so a forged or stale chunk
        would otherwise be written with its own tenant/visibility and become a
        cross-tenant leak that no retrieval-side filter can repair. This runs
        before the encoder so a foreign passage is never sent to it either.
        """
        if type(chunk) is not Chunk:
            raise ValueError("chunk must be a Chunk instance")
        for field in _CHUNK_STR_FIELDS:
            if type(getattr(chunk, field)) is not str:
                raise ValueError(f"chunk field {field!r} must be a plain string")
        for field in _CHUNK_INT_FIELDS:
            if type(getattr(chunk, field)) is not int:
                raise ValueError(f"chunk field {field!r} must be a plain integer")
        if not chunk.chunk_id:
            raise ValueError("chunk_id is required")
        if (
            chunk.document_id != snapshot.document_id
            or chunk.tenant_id != snapshot.tenant_id
            or chunk.owner_id != snapshot.owner_id
            or chunk.visibility != snapshot.visibility
            or chunk.classification != snapshot.classification
            or chunk.doc_version != snapshot.doc_version
            or chunk.acl_version != snapshot.acl_version
            or chunk.source_uri != snapshot.source_uri
            or chunk.source_sha != snapshot.source_sha
            or chunk.content_hash not in ("", snapshot.source_sha)
            or _canonical_identifiers(chunk.allowed_groups, "chunk allowed_groups")
            != snapshot.allowed_groups
            or _canonical_identifiers(chunk.allowed_users, "chunk allowed_users")
            != snapshot.allowed_users
        ):
            raise ValueError("chunk conflicts with its source document")
        start, end = chunk.start_offset, chunk.end_offset
        # Offsets are the only link between the stored passage and the
        # document bytes: a document-wide hash cannot detect a forged text,
        # and negative or inverted bounds would silently slice something else
        # (or nothing) instead of failing.
        if (
            not 0 <= start < end <= len(snapshot.content)
            or snapshot.content[start:end] != chunk.text
        ):
            raise ValueError("chunk text does not match its source document")

    def _assert_point_matches_document(
        self,
        snapshot: _DocumentSnapshot,
        point: dict[str, Any],
    ) -> None:
        """Validate the point actually about to be written, not the Chunk.

        The payload and the point ID are built after the encoder callback runs,
        from values the caller still owns: only re-reading the serialized point
        proves what Qdrant will store (and that the ID is derived from the
        verified chunk identity rather than a forged one).
        """
        try:
            decoded = json.loads(json.dumps(point, allow_nan=False, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            raise ValueError("point is not canonical JSON") from exc
        if type(decoded) is not dict or set(decoded) != {"id", "vector", "payload"}:
            raise ValueError("point structure is invalid")
        if type(decoded["id"]) is not str or not decoded["id"]:
            raise ValueError("point id must be a nonempty string")
        payload = decoded["payload"]
        if type(payload) is not dict or set(payload) != _PAYLOAD_FIELDS:
            raise ValueError("point payload fields are invalid")
        for field in _PAYLOAD_STR_FIELDS:
            if type(payload[field]) is not str:
                raise ValueError(f"payload field {field!r} must be a plain string")
        for field in _PAYLOAD_INT_FIELDS:
            if type(payload[field]) is not int:
                raise ValueError(f"payload field {field!r} must be a plain integer")
        for field in _PAYLOAD_LIST_FIELDS:
            _canonical_identifiers(payload[field], f"payload {field}")
        if payload["tombstone"] is not False:
            raise ValueError("a replacement point must not be a tombstone")
        start, end = payload["start_offset"], payload["end_offset"]
        if (
            payload["document_id"] != snapshot.document_id
            or payload["tenant_id"] != snapshot.tenant_id
            or payload["owner_id"] != snapshot.owner_id
            or payload["visibility"] != snapshot.visibility
            or payload["classification"] != snapshot.classification
            or payload["doc_version"] != snapshot.doc_version
            or payload["acl_version"] != snapshot.acl_version
            or payload["source_uri"] != snapshot.source_uri
            or payload["source_sha"] != snapshot.source_sha
            or payload["content_hash"] != snapshot.source_sha
            or tuple(payload["allowed_group_ids"]) != snapshot.allowed_groups
            or tuple(payload["allowed_user_ids"]) != snapshot.allowed_users
            or not payload["chunk_id"]
        ):
            raise ValueError("point payload conflicts with its source document")
        if (
            not 0 <= start < end <= len(snapshot.content)
            or snapshot.content[start:end] != payload["text"]
        ):
            raise ValueError("point text does not match its source document")
        self._assert_point_vector(decoded["vector"])

    def _assert_point_vector(self, vector: object) -> None:
        expected_names = {"dense", "sparse"} if self._embed_hybrid else {"dense"}
        if type(vector) is not dict or set(vector) != expected_names:
            raise ValueError("point vectors do not match the collection schema")
        dense = vector["dense"]
        if (
            type(dense) is not list
            or not dense
            or any(
                type(value) not in (int, float) or not math.isfinite(value)
                for value in dense
            )
        ):
            raise ValueError("dense vector must be a nonempty list of finite numbers")
        if self._vector_size is not None and len(dense) != self._vector_size:
            raise ValueError("dense vector size does not match the collection")
        if "sparse" not in vector:
            return
        sparse = vector["sparse"]
        if type(sparse) is not dict or set(sparse) != {"indices", "values"}:
            raise ValueError("sparse vector structure is invalid")
        indices, values = sparse["indices"], sparse["values"]
        if (
            type(indices) is not list
            or type(values) is not list
            or not indices
            or len(indices) != len(values)
            or len(set(indices)) != len(indices)
            or any(
                type(index) is not int or not 0 <= index < _MAX_SPARSE_TOKEN_ID
                for index in indices
            )
            or any(
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value <= 0
                for value in values
            )
        ):
            raise ValueError("sparse vector is invalid")

    def replace_document(
        self,
        document: Document,
        chunks: Iterable[Chunk],
    ) -> QdrantReplaceResult:
        self._assert_document_owner(document)
        # Snapshot first: the ACL containers belong to the caller, so values
        # read after the encoder callback could differ from those verified.
        snapshot = _snapshot_document(document)
        materialized = list(chunks)
        points: list[dict[str, Any]] = []
        for chunk in materialized:
            self._assert_chunk_matches_document(snapshot, chunk)
            if self._embed_hybrid is None:
                points.append(chunk_to_point(chunk, self._embed(chunk.text)))
            else:
                encoded = self._embed_hybrid(chunk.text)
                if type(encoded) is not tuple or len(encoded) != 2:
                    raise ValueError("embed_hybrid must return a (dense, sparse) pair")
                dense, sparse = encoded
                if sparse is None:
                    raise ValueError("embed_hybrid must return sparse weights")
                points.append(chunk_to_point(chunk, dense, sparse_weights=sparse))
        for point in points:
            self._assert_point_matches_document(snapshot, point)
        new_point_ids = [point["id"] for point in points]
        if len(set(new_point_ids)) != len(new_point_ids):
            # Two chunks sharing a point ID would overwrite each other: the
            # write would silently store fewer passages than reported.
            raise ValueError("chunks produce duplicate point identifiers")
        if points:
            # Upsert the new revision first so a failure never leaves the
            # document deleted (compensating write, not a silent gap).
            self._client.upsert(self._collection, points)
        # Delete every stale point of this (tenant, document) that is not part
        # of the revision we just wrote.
        query_filter: dict[str, Any] = {
            "must": [
                {"key": "tenant_id", "match": {"value": snapshot.tenant_id}},
                {"key": "document_id", "match": {"value": snapshot.document_id}},
            ]
        }
        if new_point_ids:
            query_filter["must_not"] = [{"has_id": new_point_ids}]
        self._client.delete_points(self._collection, query_filter)
        return QdrantReplaceResult(snapshot.document_id, len(materialized))


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
            if not isinstance(point, dict) or (
                type(point.get("score")) not in (int, float)
                or not math.isfinite(point["score"])
            ):
                raise ValueError("Qdrant candidate score is invalid")
            chunk = self._chunk_from_point(point)
            # Do not let coercion in _chunk_from_point erase the raw Qdrant
            # identity or JSON types: int(True) == 1 and a reconstructed point
            # ID says nothing about the ID returned by the query. A mismatched
            # candidate aborts instead of silently becoming an honest abstention
            # or a seemingly well-provenanced citation.
            canonical = chunk_to_point(chunk, [1.0])
            try:
                raw_payload = json.dumps(
                    point["payload"], sort_keys=True, allow_nan=False
                )
                decoded_payload = json.dumps(
                    canonical["payload"], sort_keys=True, allow_nan=False
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Qdrant candidate point is invalid") from exc
            if type(point.get("id")) is not str or point["id"] != canonical["id"] or raw_payload != decoded_payload:
                raise ValueError("Qdrant candidate point conflicts with decoded chunk")
            if not filter_authorized([chunk], context):
                continue
            results.append(SearchResult(chunk=chunk, score=float(point["score"])))
        return results
