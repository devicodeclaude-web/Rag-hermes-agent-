"""Read-only diagnostics of an anchored canonical copy against a Qdrant index.

Nothing here repairs anything or authorizes resuming service: the operator must
stop all writers and independently approve the anchor digest, tokenizer and
collection. Neither the local lock nor a Qdrant scroll is a distributed snapshot.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, cast
import uuid

from .acl import Chunk
from .canonical_registry import (
    CanonicalDocumentRegistry, CanonicalStoreError, _ANCHOR_FILENAME,
    _STORE_FILENAME, _TRANSACTION_LOCK_FILENAME, _close_tracked_private_file,
    _open_private_dir, _open_private_file, _open_tracked_private_file,
    _read_recovery_file,
)
from .index_integrity import IndexSnapshotReport, audit_qdrant_index
from .ingestion import Document
from .qdrant_store import chunk_to_point
from .redacted_repr import safe_count, safe_length


@contextmanager
def _verified_copy_manifest(
    copy_dir: str | Path, *, anchor_sha256: str, collection: str,
    chunker: Callable[[Document], list[Chunk]], page_size: int,
):
    """Hold a SHARED read-only lease, replay the copy, yield its manifest.

    Yields `(chunks, recheck)`. `recheck()` must be called after the remote
    read: it re-reads the anchor and the documents and re-compares the opened
    directory with the visible path, so a copy changed by a non-cooperating
    writer during the scan can never produce a result.

    `collection` and `page_size` are validated here and not used afterwards:
    both callers scan remotely with them, and failing early keeps the refusal
    on the local side, before any network call.
    """
    if type(anchor_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", anchor_sha256) is None:
        raise ValueError("independently approved anchor digest required")
    path = Path(copy_dir)
    if not path.is_absolute():
        raise ValueError("absolute canonical copy path required")
    if not collection or type(page_size) is not int or not 1 <= page_size <= 1000:
        raise ValueError("collection and bounded page_size are required")
    if not callable(chunker):
        raise ValueError("chunker must be callable")

    directory = _open_private_dir(path)
    try:
        # `write=False` everywhere: the diagnostic must stay usable on
        # read-only media, and must never let the ordinary registry guard
        # create a missing lock file.
        lock_fd, lock_token = _open_tracked_private_file(
            directory, write=False, create=False, name=_TRANSACTION_LOCK_FILENAME,
        )
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            file_fd = _open_private_file(directory, write=False, create=False, name=_STORE_FILENAME)
            os.close(file_fd)
            anchor = CanonicalDocumentRegistry._read_anchor_file(directory)
            if anchor is None or anchor[0] == 0:
                raise CanonicalStoreError("nonempty canonical anchor required")
            original_anchor = _read_recovery_file(directory, _ANCHOR_FILENAME)
            if hashlib.sha256(original_anchor).hexdigest() != anchor_sha256:
                raise ValueError("canonical anchor digest differs from approved pin")
            # The registry verifies the full replay against the anchor before
            # any remote call. No file or lock is created on this path.
            registry = CanonicalDocumentRegistry(path)
            # Last-active snapshot per document (+ the currently inactive ids):
            # a masked document keeps its old Qdrant payload, so the historical
            # record — not the inactive one — regenerates the indexed chunks.
            manifest, tombstoned_ids = registry.last_active_manifest()
            if not manifest:
                # Defence in depth, expected unreachable: a non-zero anchor
                # implies at least one replayed record, and every record
                # yields a document. Mutation testing confirms no test can
                # kill it, so it is annotated rather than pinned by a vacant
                # test.
                raise ValueError("canonical copy contains no documents")
            chunks: list[Chunk] = []
            expected_tombstone_ids: set[str] = set()
            for document_id, document in manifest.items():
                passages = list(chunker(document))
                if not passages:
                    # Checking the TOTAL only would let a document without any
                    # passage vanish from the comparison: a false match.
                    raise ValueError("canonical document produced no chunks")
                chunks.extend(passages)
                if document_id in tombstoned_ids:
                    for passage in passages:
                        expected_tombstone_ids.add(chunk_to_point(passage, [1.0])["id"])
            frozen_tombstones = frozenset(expected_tombstone_ids)

            def recheck() -> None:
                if (_read_recovery_file(directory, _ANCHOR_FILENAME) != original_anchor
                        or registry.last_active_manifest() != (manifest, tombstoned_ids)):
                    raise CanonicalStoreError("canonical copy changed during index read")
                opened = os.fstat(directory)
                visible = os.stat(path, follow_symlinks=False)
                if (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino):
                    raise CanonicalStoreError("canonical copy path changed during index read")

            yield chunks, recheck, frozen_tombstones
        finally:
            _close_tracked_private_file(lock_token)
    finally:
        os.close(directory)


def audit_canonical_copy_index(
    copy_dir: str | Path, *, anchor_sha256: str, client: Any,
    collection: str, chunker: Callable[[Document], list[Chunk]],
    page_size: int = 100,
) -> IndexSnapshotReport:
    """Compare all current documents' chunks to unfiltered Qdrant pages.

    A matching report proves only that the observed point IDs and payloads
    matched the supplied copy at scan time; vectors, hidden writes and later
    requests are not attested. `client` must be a separately credentialed,
    read-only operator client; `chunker` must be the service's approved profile.
    """
    with _verified_copy_manifest(
        copy_dir, anchor_sha256=anchor_sha256, collection=collection,
        chunker=chunker, page_size=page_size,
    ) as (chunks, recheck, expected_tombstone_ids):
        # `expected_manifest_sha256` is deliberately NOT passed: here the
        # independently approved value is the ANCHOR digest, and the manifest
        # is derived from the anchored documents by the approved chunker.
        # Pinning a manifest digest as well would only restate that
        # derivation, not add an independent source.
        report = audit_qdrant_index(
            client, collection, chunks, page_size=page_size,
            expected_tombstone_ids=expected_tombstone_ids,
        )
        recheck()
        return report


# Alias d'identité sur la garde PARTAGÉE (`rag_hermes/redacted_repr.py`), pas
# une copie : les types de résultat G1 audités revendiquent la même politique
# de représentation, et deux implémentations privées pourraient rediverger en
# silence. Un test `assertIs` épingle cette identité.
_safe_count = safe_count


@dataclass(frozen=True)
class CanonicalIndexDivergence:
    """What an operator must repair. NOT an audit verdict, and never a pass.

    Point identifiers and payload FIELD NAMES only: no document text or ACL
    values. The in-memory plan can contain hostile unknown field names;
    its repr/str are redacted to validated counts (even for forged counter
    types), but do not serialise/log its raw attributes or
    dataclasses.asdict(plan). Use render_divergence_report for a safe
    operator-facing view. An empty plan is not proof of concordance either:
    only `audit_canonical_copy_index` is the fail-closed gate.
    """

    expected_point_count: int
    observed_point_count: int
    missing_point_ids: tuple[str, ...]
    unexpected_point_ids: tuple[str, ...]
    divergent_points: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def is_clean(self) -> bool:
        return not (self.missing_point_ids or self.unexpected_point_ids
                    or self.divergent_points)

    def __repr__(self) -> str:
        # Dataclass' default repr would log hostile index-controlled field
        # names and point IDs. Preserve the full plan for programmatic repair,
        # but make accidental logging show only safe, bounded counts. A caller
        # may also instantiate this public dataclass with forged counter types,
        # so EVERY field goes through the shared guard: a bare `len()` leaked a
        # forged string's length, raised `TypeError` on an int, and copied a
        # hostile `__len__`'s message — hence the index's text — into the
        # traceback that gets logged.
        return (
            "CanonicalIndexDivergence("
            f"expected_point_count={_safe_count(getattr(self, 'expected_point_count', None))}, "
            f"observed_point_count={_safe_count(getattr(self, 'observed_point_count', None))}, "
            f"missing_count={safe_length(getattr(self, 'missing_point_ids', None))}, "
            f"unexpected_count={safe_length(getattr(self, 'unexpected_point_ids', None))}, "
            f"divergent_count={safe_length(getattr(self, 'divergent_points', None))})"
        )


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        # Same contract as the audit (`verify_index_snapshot`): a library
        # caller that handles ValueError must not get a bare TypeError.
        raise ValueError("invalid indexed payload encoding") from exc


# Fixed service schema, not obtained from the index. Keep this list in sync
# with chunk_to_point's payload (the regression test checks all its keys).
# Unknown index keys can themselves be secrets and must not reach CLI logs.
_CANONICAL_PAYLOAD_FIELDS = frozenset({
    "chunk_id", "document_id", "text", "tenant_id", "visibility",
    "allowed_group_ids", "allowed_user_ids", "owner_id", "classification",
    "doc_version", "acl_version", "source_sha", "source_uri", "section",
    "start_offset", "end_offset", "token_count", "tokenizer_name",
    "tokenizer_revision", "content_hash", "tombstone",
})


def _safe_label(value: Any, kind: str, index: int) -> str:
    """Show only a Qdrant point-ID shape, never an arbitrary printable label.

    The plan normalises integer IDs to decimal strings. Both unsigned 64-bit
    integers and UUIDs are legitimate point IDs; everything else is masked,
    including printable secrets supplied by a hostile or broken index client.
    UUID forms are exact (hex, hyphenated, URN), not merely parseable prefixes.
    """
    if type(value) is str:
        if value.isascii() and value.isdecimal() and len(value) <= 20:
            number = int(value)
            if number < 2**64 and str(number) == value:
                return value
        if len(value) in (32, 36, 45):
            try:
                parsed = uuid.UUID(value)
            except ValueError:
                pass
            else:
                if value.lower() in (parsed.hex, str(parsed), f"urn:uuid:{parsed}"):
                    return value
    return f"<{kind} masqué n°{index}>"


def render_divergence_report(
    plan: CanonicalIndexDivergence, *, max_entries: int = 200
) -> list[str]:
    """One safe line per entry, bounded, for an operator or a ticket."""
    if type(max_entries) is not int or not 1 <= max_entries <= 10_000:
        raise ValueError("max_entries must be a bounded positive int")
    # The plan is a PUBLIC dataclass, rebuildable with forged fields. Validate
    # the shape before measuring or slicing anything: a bare `len()`/`[:]` on a
    # forged field raised TypeError/IndexError out of the operator's "safe"
    # view, and a hostile `__len__`/`__getitem__` could fabricate extra report
    # lines. Fail closed with a fixed message instead of rendering a doubtful
    # report. Each field is read EXACTLY ONCE into a local: re-reading after
    # the check let a descriptor return a tuple at validation time and
    # something else at formatting time, which put the IndexError back.
    missing = getattr(plan, "missing_point_ids", None)
    unexpected = getattr(plan, "unexpected_point_ids", None)
    divergent = getattr(plan, "divergent_points", None)
    if any(type(field) is not tuple for field in (missing, unexpected, divergent)):
        raise ValueError("plan de divergence invalide")
    missing = cast(tuple, missing)
    unexpected = cast(tuple, unexpected)
    divergent = cast(tuple, divergent)
    for entry in divergent:
        if (
            type(entry) is not tuple or len(entry) != 2
            or type(entry[1]) is not tuple
        ):
            raise ValueError("plan de divergence invalide")
    lines = [
        f"Points attendus : {_safe_count(getattr(plan, 'expected_point_count', None))} ; "
        f"observés : {_safe_count(getattr(plan, 'observed_point_count', None))}."
    ]

    def section(title: str, entries: tuple, formatter) -> None:
        lines.append(f"{title} ({len(entries)}) :")
        for index, entry in enumerate(entries[:max_entries]):
            lines.append(f"  - {formatter(index, entry)}")
        hidden = len(entries) - max_entries
        if hidden > 0:
            lines.append(f"  … et {hidden} autres non affichés")

    section("Points manquants dans l'index", missing,
            lambda index, point_id: _safe_label(point_id, "identifiant", index))
    section("Points inattendus dans l'index", unexpected,
            lambda index, point_id: _safe_label(point_id, "identifiant", index))
    def format_divergent(index: int, entry: tuple[str, tuple[str, ...]]) -> str:
        # Show ALL approved fields (including ACL) even when unknown index
        # keys sort first. Unknown key names may be secrets, so count them
        # without printing them. The static schema bounds every line.
        fields = entry[1]
        approved = [field for field in fields
                    if type(field) is str and field in _CANONICAL_PAYLOAD_FIELDS]
        unknown_count = len(fields) - len(approved)
        shown = ", ".join(approved)
        if unknown_count:
            noun = "champ inconnu" if unknown_count == 1 else "champs inconnus"
            shown += f" ; {unknown_count} {noun}" if shown else f"{unknown_count} {noun}"
        return f"{_safe_label(entry[0], 'identifiant', index)} : {shown}"

    section("Points divergents", divergent, format_divergent)
    return lines


def _collect_all_points(
    client: Any, collection: str, *, page_size: int, max_points: int
) -> list[dict[str, Any]]:
    """Scroll every page with the audit's cursor discipline, but bounded.

    The audit stops at the first surplus point; a plan must enumerate them, so
    the budget is explicit and exceeding it fails closed instead of growing
    unbounded on a wildly divergent collection.
    """
    points: list[dict[str, Any]] = []
    offset: str | int | None = None
    seen_offsets: set[str | int] = set()
    while True:
        page, next_offset = client.scroll_page(collection, limit=page_size, offset=offset)
        if not isinstance(page, list) or len(page) > page_size:
            raise ValueError("invalid Qdrant scroll page")
        points.extend(page)
        if len(points) > max_points:
            # Stop the scroll instead of collecting an unbounded divergence.
            raise ValueError("divergence exceeds the reconciliation plan budget")
        if next_offset is None:
            return points
        if not page or type(next_offset) not in (str, int) or next_offset in seen_offsets:
            raise ValueError("invalid or repeated Qdrant scroll cursor")
        seen_offsets.add(next_offset)
        offset = next_offset


def plan_canonical_index_reconciliation(
    copy_dir: str | Path, *, anchor_sha256: str, client: Any,
    collection: str, chunker: Callable[[Document], list[Chunk]],
    page_size: int = 100, surplus_budget: int = 1000,
) -> CanonicalIndexDivergence:
    """Enumerate missing, unexpected and divergent points for a human repair.

    Read-only, like the audit, under the same shared lease and anchor pin. It
    writes nothing, decides nothing and authorizes no resumption: repairing the
    listed points, and re-auditing afterwards, stays the operator's call.

    `surplus_budget` caps the TOTAL number of points read at
    `expected + surplus_budget`, which is a memory/scroll bound, NOT a cap on
    how many unexpected points may be listed: with M canonical points absent
    from the index, up to `surplus_budget + M` strangers still fit under it.
    """
    if type(surplus_budget) is not int or not 0 <= surplus_budget <= 100_000:
        # `type(x) is int` on purpose: isinstance(True, int) is true, and a
        # float budget silently disables the bound (len(points) > 2.5 never
        # fires for a small page), so the scroll would grow unbounded.
        raise ValueError("surplus_budget must be a bounded non-negative int")
    with _verified_copy_manifest(
        copy_dir, anchor_sha256=anchor_sha256, collection=collection,
        chunker=chunker, page_size=page_size,
    ) as (chunks, recheck, expected_tombstone_ids):
        expected: dict[str, dict[str, Any]] = {}
        for chunk in chunks:
            point = chunk_to_point(chunk, [1.0])
            if point["id"] in expected:
                raise ValueError("duplicate canonical point id")
            if point["id"] in expected_tombstone_ids:
                # A masked document's points keep their old payload except the
                # tombstone flag, so the plan must expect them masked too.
                point["payload"]["tombstone"] = True
            expected[point["id"]] = point["payload"]

        observed: dict[str, dict[str, Any]] = {}
        for point in _collect_all_points(
            client, collection, page_size=page_size,
            max_points=len(expected) + surplus_budget,
        ):
            # Qdrant accepts integer ids, which a third-party writer may well
            # have used: refusing them in a bloc would blind the plan exactly
            # when it is needed. They are normalised for listing only and can
            # never match a canonical uuid5 identifier. `type(x) in (str,int)`
            # keeps `True` out, since isinstance(True, int) is true.
            if not isinstance(point, dict) or type(point.get("id")) not in (str, int):
                raise ValueError("invalid indexed point id")
            point_id = str(point["id"])
            if point_id in observed:
                raise ValueError("duplicate indexed point id")
            payload = point.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("invalid indexed payload")
            observed[point_id] = payload

        divergent: list[tuple[str, tuple[str, ...]]] = []
        for point_id in expected.keys() & observed.keys():
            canonical_payload, indexed_payload = expected[point_id], observed[point_id]
            # Field NAMES only: a value would copy document text or an ACL
            # into the operator's logs. Canonical JSON per field keeps
            # `true` distinct from `1`.
            fields = sorted(
                field for field in canonical_payload.keys() | indexed_payload.keys()
                if field not in canonical_payload or field not in indexed_payload
                or _canonical_json(canonical_payload[field])
                != _canonical_json(indexed_payload[field])
            )
            if fields:
                divergent.append((point_id, tuple(fields)))

        recheck()
        return CanonicalIndexDivergence(
            expected_point_count=len(expected),
            observed_point_count=len(observed),
            missing_point_ids=tuple(sorted(expected.keys() - observed.keys())),
            unexpected_point_ids=tuple(sorted(observed.keys() - expected.keys())),
            divergent_points=tuple(sorted(divergent)),
        )
