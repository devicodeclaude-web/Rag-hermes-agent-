"""Compare a complete Qdrant point snapshot to an independent chunk manifest.

This is a pure comparison, NOT a proof that a caller actually fetched all points,
that the collection is immutable, or that a subsequent query uses the same snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
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
