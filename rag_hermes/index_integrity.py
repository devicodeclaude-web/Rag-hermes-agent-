"""Compare a complete Qdrant point snapshot to an independent chunk manifest.

This is a pure comparison, NOT a proof that a caller actually fetched all points,
that the collection is immutable, or that a subsequent query uses the same snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import threading
from typing import Any, Iterable

from .acl import Chunk
from .qdrant_store import chunk_to_point


@dataclass(frozen=True)
class IndexSnapshotReport:
    point_count: int
    payload_sha256: str


def audit_qdrant_index(
    client: Any,
    collection: str,
    expected_chunks: Iterable[Chunk],
    *,
    page_size: int = 100,
) -> IndexSnapshotReport:
    """Audit unfiltered pages; caller must freeze writes for the whole audit and run."""
    if not collection or not 1 <= page_size <= 1000:
        raise ValueError("collection and bounded page_size are required")
    expected = list(expected_chunks)
    if not expected:
        raise ValueError("empty canonical chunk manifest")
    points: list[dict[str, Any]] = []
    offset: str | int | None = None
    seen_offsets: set[str | int] = set()
    while True:
        page, next_offset = client.scroll_page(collection, limit=page_size, offset=offset)
        if not isinstance(page, list) or len(page) > page_size:
            raise ValueError("invalid Qdrant scroll page")
        points.extend(page)
        if len(points) > len(expected):
            raise ValueError("unexpected indexed points")
        if next_offset is None:
            break
        if not page or type(next_offset) not in (str, int) or next_offset in seen_offsets:
            raise ValueError("invalid or repeated Qdrant scroll cursor")
        seen_offsets.add(next_offset)
        offset = next_offset
    return verify_index_snapshot(expected, points)


def verify_index_snapshot(
    expected_chunks: Iterable[Chunk], observed_points: Iterable[dict[str, Any]]
) -> IndexSnapshotReport:
    """Fail closed on missing, extra, duplicate, or mismatched indexed points."""
    expected: dict[str, dict[str, Any]] = {}
    for chunk in expected_chunks:
        point = chunk_to_point(chunk, [1.0])
        if point["id"] in expected:
            raise ValueError("duplicate canonical point id")
        expected[point["id"]] = point["payload"]
    if not expected:
        raise ValueError("empty canonical chunk manifest")

    observed: dict[str, dict[str, Any]] = {}
    for point in observed_points:
        if not isinstance(point, dict) or not isinstance(point.get("id"), str):
            raise ValueError("invalid indexed point id")
        point_id = point["id"]
        if point_id in observed:
            raise ValueError("duplicate indexed point id")
        payload = point.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("invalid indexed payload")
        observed[point_id] = payload

    missing = expected.keys() - observed.keys()
    unexpected = observed.keys() - expected.keys()
    if missing:
        raise ValueError("missing canonical indexed points")
    if unexpected:
        raise ValueError("unexpected indexed points")
    for point_id, payload in expected.items():
        try:
            canonical_payload = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                allow_nan=False,
            )
            indexed_payload = json.dumps(
                observed[point_id], ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid indexed payload encoding") from exc
        if indexed_payload != canonical_payload:
            raise ValueError("indexed payload conflicts with canonical manifest")

    canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return IndexSnapshotReport(point_count=len(expected), payload_sha256=digest)


class AuditedIndexSessionError(RuntimeError):
    """A session audit did not complete cleanly; the campaign is unusable.

    Raised for every audit-level failure at open() or close(), whatever the
    cause (manifest divergence, transport fault, malformed Qdrant reply). The
    cause is preserved in the message and in __cause__ precisely because this
    class must NOT assert which one occurred.
    """


class AuditedIndexSession:
    """Re-run the manifest audit after a campaign and fail closed on divergence.

    `open()` runs the audit, `close()` runs it again. A failed open() or close()
    is TERMINAL: the gate is closed under a lock before any audit work starts, so
    neither a retry nor a concurrent caller can turn a detected divergence into a
    pass.

    This is a voluntary building block with no caller in the query path yet. It
    does not frame, intercept or gate any query: running `open()` before the
    first evaluation query and `close()` after the last one is an OPERATOR
    obligation, not a property this class enforces. It prevents no writes, and a
    divergence reverted before `close()` — or one touching only vectors — stays
    invisible. The two reports derive from the same manifest, so their equality
    is not independent evidence; the only signal is that the closing audit re-ran
    and still passed.
    """

    def __init__(
        self,
        client: Any,
        collection: str,
        expected_chunks: Iterable[Chunk],
        *,
        page_size: int = 100,
    ) -> None:
        if not collection:
            raise ValueError("collection is required")
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        expected = list(expected_chunks)
        if not expected:
            raise ValueError("empty canonical chunk manifest")
        self._client = client
        self._collection = collection
        self._expected = expected
        self._page_size = page_size
        self._state = "new"
        self._lock = threading.Lock()
        self._opening: IndexSnapshotReport | None = None

    def _begin(self, allowed_state: str, misuse: str) -> None:
        """Close the gate ATOMICALLY, before any audit work starts.

        Checking the state and marking it terminal must happen under one lock:
        otherwise two concurrent callers both pass the check and one of them can
        return a passing report while the other detects a divergence.
        """
        with self._lock:
            if self._state != allowed_state:
                raise ValueError(misuse)
            self._state = "finished"

    def _audit(self, label: str) -> IndexSnapshotReport:
        try:
            return audit_qdrant_index(
                self._client, self._collection, self._expected, page_size=self._page_size
            )
        except Exception as exc:
            # Fixed message on purpose: the cause may embed a Qdrant URL,
            # credentials or a response body. It stays in __cause__ for logs.
            raise AuditedIndexSessionError(f"{label} audit failed") from exc

    def open(self) -> IndexSnapshotReport:
        self._begin("new", "audited index session is already opened or finished")
        self._opening = self._audit("opening")
        self._state = "open"
        return self._opening

    def close(self) -> IndexSnapshotReport:
        if self._state == "new":
            raise ValueError("audited index session was not opened")
        self._begin("open", "audited index session is already finished")
        closing = self._audit("closing")
        if closing != self._opening:
            # Defence in depth, expected to be unreachable: both reports are
            # derived from the same frozen manifest, so they cannot differ once
            # both audits pass. Kept as an assertion, not as corroboration.
            raise AuditedIndexSessionError("closing report disagreed with the opening report")
        return closing
