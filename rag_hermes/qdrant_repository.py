from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import unicodedata
from typing import Any, Callable, Iterable, cast

from .acl import AuthorizationContext, Chunk, filter_authorized
from .ingestion import Document
from .qdrant_filter import build_qdrant_filter
from .qdrant_preflight import verify_collection_ready
from .qdrant_store import chunk_to_point, lexical_weights_to_sparse_vector, stable_point_id
from .qdrant_write_lock import default_lock_directory, document_write_lock
from .retrieval import SearchResult


_OWNER_SCAN_PAGE_SIZE = 10_000
_OWNER_SCAN_BUDGET = 100_000

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


def _assert_no_control_characters(value: str, field: str) -> None:
    """Identity fields must stay free of control characters.

    They are concatenated into the point identity key; a client-supplied
    document_id carrying U+001F is the kind of input that turns an encoding
    into a collision. The key is injective on its own, this is the second
    lock.
    """
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError(f"{field} must not contain control characters")


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
    for field in ("document_id", "tenant_id", "owner_id"):
        _assert_no_control_characters(getattr(document, field), f"document {field}")
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
class HybridCandidate:
    """RRF candidate, not a calibrated answer score or an ACL attestation.

    `authorized_by_index` has no default on purpose: a construction site that
    forgets it must fail loudly instead of minting a candidate that claims the
    payload ACL accepted it.
    """

    chunk: Chunk
    rrf_score: float
    authorized_by_index: bool


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
        vector_size: int | None = None,
        lock_dir: str | Path | None = None,
        lock_timeout: float = 30.0,
    ) -> None:
        if not collection.strip():
            raise ValueError("collection is required")
        if not callable(embed):
            raise ValueError("embed must be callable")
        if embed_hybrid is not None and not callable(embed_hybrid):
            raise ValueError("embed_hybrid must be callable")
        self._client = client
        # Strip once: the preflight normalizes the name, so keeping the padded
        # value would verify one collection and write to another.
        self._collection = collection.strip()
        self._embed = embed
        self._embed_hybrid = embed_hybrid
        self._lock_dir = Path(lock_dir) if lock_dir is not None else default_lock_directory()
        if not self._lock_dir.is_absolute():
            raise ValueError("lock directory must be an absolute path")
        if type(lock_timeout) not in (int, float) or not 0 <= lock_timeout <= 3600:
            raise ValueError("document lock timeout must be between 0 and 3600 seconds")
        self._lock_timeout = lock_timeout
        if vector_size is not None and (
            type(vector_size) is not int or vector_size < 1
        ):
            raise ValueError("vector_size must be a positive integer")
        # The dense-only path cannot read collection metadata (its clients are
        # not required to expose it), so a caller that already ran the
        # preflight passes the verified size in.
        self._vector_size: int | None = vector_size
        # Unknown distance accepts only exact readback; a real REST client
        # exposes metadata so Cosine normalization can be verified explicitly.
        self._dense_distance: str | None = None
        if embed_hybrid is not None:
            schema = verify_collection_ready(
                client, self._collection, require_sparse=True
            )
            if vector_size is not None and vector_size != schema["vector_size"]:
                raise ValueError("vector_size does not match the collection")
            self._vector_size = schema["vector_size"]
            self._dense_distance = "Cosine"  # verified by hybrid preflight

    def _assert_document_owner(self, snapshot: _DocumentSnapshot) -> set[str | int]:
        # A short page is not proof of completion: only Qdrant's terminal
        # cursor is. Repeated/malformed cursors or a budget overrun fail closed.
        query_filter = {
            "must": [
                {"key": "tenant_id", "match": {"value": snapshot.tenant_id}},
                {"key": "document_id", "match": {"value": snapshot.document_id}},
            ],
        }
        offset: str | int | None = None
        scroll_page = cast(Any, getattr(self._client, "scroll_filtered_page", None))
        if not callable(scroll_page):
            raise RuntimeError(
                "Qdrant client must implement scroll_filtered_page with a terminal cursor"
            )
        seen_offsets: set[str | int] = set()
        seen_ids: set[str | int] = set()
        scanned = 0
        while True:
            page, next_offset = scroll_page(
                self._collection, query_filter=query_filter,
                limit=_OWNER_SCAN_PAGE_SIZE, offset=offset,
            )
            if type(page) is not list or len(page) > _OWNER_SCAN_PAGE_SIZE:
                raise PermissionError("document owner scan is incomplete")
            scanned += len(page)
            if scanned > _OWNER_SCAN_BUDGET:
                raise PermissionError("document owner scan exceeds budget")
            for point in page:
                payload = point.get("payload") if type(point) is dict else None
                point_id = point.get("id") if type(point) is dict else None
                if (
                    type(payload) is not dict
                    or type(point_id) not in (str, int)
                    or isinstance(point_id, str) and not point_id
                    or isinstance(point_id, int) and point_id < 0
                    or point_id in seen_ids
                ):
                    raise PermissionError("document owner payload is invalid")
                seen_ids.add(cast(str | int, point_id))
                if (
                    type(payload.get("tenant_id")) is not str
                    or payload["tenant_id"] != snapshot.tenant_id
                    or type(payload.get("document_id")) is not str
                    or payload["document_id"] != snapshot.document_id
                    or type(payload.get("owner_id")) is not str
                    or payload["owner_id"] != snapshot.owner_id
                ):
                    raise PermissionError("only the existing document owner can replace it")
            if next_offset is None:
                return seen_ids
            if (
                type(next_offset) not in (str, int)
                or isinstance(next_offset, str) and not next_offset
                or isinstance(next_offset, int) and next_offset < 0
                or not page
                or next_offset in seen_offsets
            ):
                raise PermissionError("document owner scan cursor is invalid")
            seen_offsets.add(next_offset)
            offset = next_offset

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
        _assert_no_control_characters(chunk.chunk_id, "chunk_id")
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
    ) -> dict[str, Any]:
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
        # The ID decides which stored point this write replaces, so it must be
        # derived from the identity just verified and from nothing else.
        if decoded["id"] != stable_point_id(
            tenant_id=snapshot.tenant_id,
            document_id=snapshot.document_id,
            chunk_id=payload["chunk_id"],
            source_sha=snapshot.source_sha,
            doc_version=snapshot.doc_version,
        ):
            raise ValueError("point id is not derived from the verified identity")
        self._assert_point_vector(decoded["vector"])
        return decoded

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
        if "sparse" not in expected_names:
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

    def _readback_vector_matches(self, expected: dict[str, Any], actual: object) -> bool:
        """Compare Qdrant's float32 vectors against its configured distance.

        A skipped upsert can leave the expected payload/ID with an old vector.
        Dense vectors may be stored unit-normalized only for Cosine distance;
        sparse indices may be reordered on retrieval.
        """
        if type(actual) is not dict or set(actual) != set(expected):
            return False
        dense = actual["dense"]
        wanted = expected["dense"]
        if type(dense) is not list or len(dense) != len(wanted) or any(
            type(value) not in (int, float) or not math.isfinite(value)
            for value in dense
        ):
            return False
        norm = math.hypot(*wanted)
        normalized = [value / norm for value in wanted] if norm else wanted
        if not (
            all(math.isclose(value, original, rel_tol=1e-5, abs_tol=0.0)
                for value, original in zip(dense, wanted))
            or (self._dense_distance == "Cosine" and all(
                math.isclose(value, unit, rel_tol=1e-5, abs_tol=0.0)
                for value, unit in zip(dense, normalized)
            ))
        ):
            return False
        if "sparse" not in expected:
            return True
        sparse = actual["sparse"]
        if type(sparse) is not dict or set(sparse) != {"indices", "values"}:
            return False
        indices, values = sparse["indices"], sparse["values"]
        if (
            type(indices) is not list or type(values) is not list
            or len(indices) != len(values)
            or any(type(i) is not int for i in indices)
            or len(set(indices)) != len(indices)
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
        ):
            return False
        wanted_sparse = expected["sparse"]
        wanted_values = dict(zip(wanted_sparse["indices"], wanted_sparse["values"]))
        return set(indices) == set(wanted_values) and all(
            math.isclose(value, wanted_values[index], rel_tol=1e-5, abs_tol=0.0)
            for index, value in zip(indices, values)
        )

    def replace_document(
        self,
        document: Document,
        chunks: Iterable[Chunk],
    ) -> QdrantReplaceResult:
        if type(document) is not Document:
            raise ValueError("document must be a Document instance")
        # Snapshot first, and verify ownership against the snapshot: the ACL
        # containers belong to the caller, so a value read before the encoder
        # callback could differ from the one that ends up in the payload.
        snapshot = _snapshot_document(document)
        with document_write_lock(
            self._lock_dir, self._collection, snapshot.tenant_id, snapshot.document_id,
            timeout=self._lock_timeout,
        ):
            return self._replace_document_locked(snapshot, chunks)

    def _replace_document_locked(
        self, snapshot: _DocumentSnapshot, chunks: Iterable[Chunk]
    ) -> QdrantReplaceResult:
        # The lock must cover metadata, the full owner scan, encoding, write,
        # readback and deletion. Splitting it would reopen the ID reuse race.
        if self._embed_hybrid is None:
            get_collection = getattr(self._client, "get_collection", None)
            if callable(get_collection):
                metadata = get_collection(self._collection)
                try:
                    dense_config = metadata["config"]["params"]["vectors"]["dense"]
                    distance = dense_config["distance"]
                    datatype = dense_config.get("datatype")
                except (KeyError, TypeError, AttributeError) as exc:
                    raise RuntimeError("Qdrant dense distance metadata is invalid") from exc
                if type(distance) is not str or distance not in {"Cosine", "Dot", "Euclid", "Manhattan"}:
                    raise RuntimeError("Qdrant dense distance metadata is invalid")
                if datatype not in (None, "float32"):
                    raise RuntimeError("Qdrant dense datatype must be float32 for readback verification")
                self._dense_distance = distance
            else:
                self._dense_distance = None  # injected clients without metadata: strict exact comparison
        old_ids = self._assert_document_owner(snapshot)
        readback = getattr(self._client, "retrieve_points", None)
        if not callable(readback):
            raise RuntimeError("Qdrant client must implement retrieve_points for conditional upsert verification")
        materialized = list(chunks)
        if not materialized:
            raise ValueError("a replacement must carry at least one passage")
        built: list[dict[str, Any]] = []
        for chunk in materialized:
            self._assert_chunk_matches_document(snapshot, chunk)
            if self._embed_hybrid is None:
                built.append(chunk_to_point(chunk, self._embed(chunk.text)))
            else:
                encoded = self._embed_hybrid(chunk.text)
                if not isinstance(encoded, (tuple, list)) or len(encoded) != 2:
                    raise ValueError("embed_hybrid must return a (dense, sparse) pair")
                dense, sparse = encoded
                if sparse is None:
                    raise ValueError("embed_hybrid must return sparse weights")
                built.append(chunk_to_point(chunk, dense, sparse_weights=sparse))
        # Write the validated projection, so what was checked is what is sent.
        points = [
            self._assert_point_matches_document(snapshot, point) for point in built
        ]
        new_point_ids = [point["id"] for point in points]
        if len(set(new_point_ids)) != len(new_point_ids):
            # Two chunks sharing a point ID would overwrite each other: the
            # write would silently store fewer passages than reported.
            raise ValueError("chunks produce duplicate point identifiers")
        # The server checks the OLD payload at the moment of the upsert.
        # New IDs are inserted even if update_filter would not match: read back
        # every requested ID before a delete, since a skipped update is silent.
        guard = {"must": [
            {"key": "tenant_id", "match": {"value": snapshot.tenant_id}},
            {"key": "document_id", "match": {"value": snapshot.document_id}},
            {"key": "owner_id", "match": {"value": snapshot.owner_id}},
        ], "must_not": [
            {"key": "tenant_id", "match": {"except": [snapshot.tenant_id]}},
            {"key": "document_id", "match": {"except": [snapshot.document_id]}},
            {"key": "owner_id", "match": {"except": [snapshot.owner_id]}},
        ]}
        response = self._client.upsert(self._collection, points, update_filter=guard)
        if (
            type(response) is not dict or response.get("status") != "ok"
            or type(response.get("result")) is not dict
            or response["result"].get("status") != "completed"
        ):
            raise RuntimeError("Qdrant conditional upsert did not complete")
        persisted = readback(self._collection, new_point_ids)
        if type(persisted) is not list or len(persisted) != len(new_point_ids):
            raise PermissionError("conditional upsert did not persist every point")
        expected = {point["id"]: point for point in points}
        seen: set[str] = set()
        for point in persisted:
            point_id = point.get("id") if type(point) is dict else None
            if (
                type(point_id) is not str or point_id not in expected
                or point_id in seen or type(point.get("payload")) is not dict
                or point["payload"] != expected[point_id]["payload"]
                or not self._readback_vector_matches(
                    expected[point_id]["vector"], point.get("vector")
                )
            ):
                raise PermissionError("conditional upsert verification failed")
            seen.add(point_id)
        # Delete only IDs actually seen in a completed owner scan. Keep the
        # tenant/document/owner predicates as defense against a later scalar
        # owner change; this is NOT a lock against ID reuse or array payloads.
        stale_ids = old_ids.difference(new_point_ids)
        if not stale_ids:
            return QdrantReplaceResult(snapshot.document_id, len(materialized))
        query_filter: dict[str, Any] = {
            "must": [
                *guard["must"],
                {"has_id": sorted(stale_ids, key=str)},
            ],
            "must_not": guard["must_not"],
        }
        delete_response = self._client.delete_points(self._collection, query_filter)
        if (
            type(delete_response) is not dict or delete_response.get("status") != "ok"
            or type(delete_response.get("result")) is not dict
            or delete_response["result"].get("status") != "completed"
        ):
            raise RuntimeError("Qdrant delete did not complete")
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

    def _verified_query_point(self, point: object) -> tuple[str, Chunk, str]:
        """Check a raw query hit before ACL filtering can hide corruption."""
        if type(point) is not dict or (
            type(point.get("score")) not in (int, float)
            or not math.isfinite(point["score"])
        ):
            raise ValueError("Qdrant candidate score is invalid")
        chunk = self._chunk_from_point(point)
        canonical = chunk_to_point(chunk, [1.0])
        try:
            raw_payload = json.dumps(point["payload"], sort_keys=True, allow_nan=False)
            decoded_payload = json.dumps(canonical["payload"], sort_keys=True, allow_nan=False)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Qdrant candidate point is invalid") from exc
        if type(point.get("id")) is not str or point["id"] != canonical["id"] or raw_payload != decoded_payload:
            raise ValueError("Qdrant candidate point conflicts with decoded chunk")
        return point["id"], chunk, raw_payload

    def hybrid_candidates(
        self, query: str, *, context: AuthorizationContext, output_limit: int = 40,
        include_denied: bool = False,
    ) -> list[HybridCandidate]:
        """Fetch dense/sparse top-40 and fuse by RRF; NEVER use RRF as a quality gate.

        These candidates still need a trusted canonical ACL/provenance source,
        reranking and a calibrated abstention rule before any answer or citation.
        `include_denied` additionally returns hits rejected by the local
        payload ACL when the injected client did not already prefilter them,
        flagged `authorized_by_index=False`. With the real Qdrant server the
        ACL prefilter removes such points BEFORE either query response, so
        this flag CANNOT generally detect an index that is more restrictive
        than the canonical source. Flagged hits are diagnostics for internal
        callers only; never pass them to generation, citations or users.
        """
        if type(include_denied) is not bool:
            raise ValueError("include_denied must be a boolean")
        if self._embed_hybrid is None:
            raise ValueError("hybrid candidates require a hybrid encoder")
        if type(output_limit) is not int or not 1 <= output_limit <= 80:
            raise ValueError("hybrid output_limit must be between 1 and 80")
        if (
            type(context) is not AuthorizationContext
            or type(context.tenant_id) is not str or not context.tenant_id
            or type(context.user_id) is not str or not context.user_id
            or type(context.groups) is not tuple
            or any(type(group) is not str or not group for group in context.groups)
            or type(context.clearance) is not int or context.clearance < 0
        ):
            raise ValueError("valid authorization context is required")
        dense, sparse = self._embed_hybrid(query)
        if (
            type(dense) is not list or len(dense) != self._vector_size
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in dense)
        ):
            raise ValueError("hybrid query dense vector is invalid")
        lexical_weights_to_sparse_vector(sparse)
        query_sparse = getattr(self._client, "query_sparse", None)
        if not callable(query_sparse):
            raise RuntimeError("Qdrant client must implement query_sparse")
        dense_hits = self._client.query(
            self._collection, dense, query_filter=build_qdrant_filter(context), limit=40,
        )
        sparse_hits = query_sparse(
            self._collection, sparse, context=context, limit=40,
        )
        scores: dict[str, float] = {}
        chunks: dict[str, Chunk] = {}
        payloads: dict[str, str] = {}
        for hits in (dense_hits, sparse_hits):
            if type(hits) is not list or len(hits) > 40:
                raise ValueError("Qdrant hybrid candidate page is invalid")
            lane: list[tuple[str, Chunk, str, float]] = []
            seen: set[str] = set()
            for hit in hits:
                point_id, chunk, payload = self._verified_query_point(hit)
                if point_id in seen:
                    raise ValueError("duplicate Qdrant candidate in a lane")
                seen.add(point_id)
                lane.append((point_id, chunk, payload, float(hit["score"])))
            lane.sort(key=lambda item: (-item[3], item[0]))
            for rank, (point_id, chunk, payload, _score) in enumerate(lane, 1):
                if point_id in payloads and payloads[point_id] != payload:
                    raise ValueError("conflicting Qdrant candidate across lanes")
                payloads[point_id] = payload
                chunks[point_id] = chunk
                scores[point_id] = scores.get(point_id, 0.0) + 1.0 / (60 + rank)
        # The prefilter is only an optimization: recheck the decoded ACL before
        # the output cap, so a foreign top hit never hides an authorized hit.
        ordered = sorted(scores, key=lambda point_id: (-scores[point_id], point_id))
        authorized: list[HybridCandidate] = []
        denied: list[HybridCandidate] = []
        for point_id in ordered:
            if filter_authorized([chunks[point_id]], context):
                authorized.append(HybridCandidate(
                    chunks[point_id], scores[point_id], authorized_by_index=True,
                ))
            elif include_denied:
                denied.append(HybridCandidate(
                    chunks[point_id], scores[point_id], authorized_by_index=False,
                ))
        # The cap bounds the AUTHORIZED candidates; the denied ones are extra
        # diagnostics, so asking for them never shrinks the usable window.
        return authorized[:output_limit] + denied

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
            _point_id, chunk, _payload = self._verified_query_point(point)
            if not filter_authorized([chunk], context):
                continue
            results.append(SearchResult(chunk=chunk, score=float(point["score"])))
        return results
