"""One-shot, candidate-only G1 window bracketed by two Qdrant payload audits.

Neither audit freezes writes, checks vectors, or proves the query saw the same
snapshot. An empty candidate window is NOT an honest abstention verdict.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path

from .acl import AuthorizationContext, Chunk
from .canonical_snapshot import load_pinned_document_snapshot
from .g1_hybrid_candidates import CanonicalHybridCandidates
from .g1_reranking import RerankedCandidate, RerankedCandidateSource
from .index_integrity import AuditedIndexSession, IndexSnapshotReport
from .ingestion import Document
from .qdrant_repository import HybridCandidate, QdrantChunkRepository
from .qdrant_rest import QdrantAuditRestClient, QdrantRestClient
from .qdrant_store import chunk_to_point
from .retrieval import CanonicalAclError


@dataclass(frozen=True)
class AuditedCandidateWindow:
    """Uncalibrated candidates, plus the two completed payload audit reports."""

    candidates: tuple[RerankedCandidate, ...]
    opening: IndexSnapshotReport
    closing: IndexSnapshotReport


def _dense_only_disabled(_query: str) -> list[float]:
    raise ValueError("this candidate-only path requires a hybrid encoder")


def run_audited_g1_candidate_window(
    *,
    base_url: str,
    collection: str,
    source_path: Path,
    expected_source_sha256: str,
    expected_manifest_sha256: str,
    chunker: Callable[[Document], list[Chunk]],
    embed_hybrid: Callable[[str], tuple[list[float], dict[str, float]]],
    reranker: object,
    tokenizer: object,
    question: str,
    context: AuthorizationContext,
    candidate_limit: int = 20,
    top_k: int = 8,
    max_length: int = 512,
    batch_size: int = 1,
) -> AuditedCandidateWindow:
    """Audit, retrieve and rerank, audit again, *then* release candidates.

    The two clients are constructed here from the SAME base URL and collection,
    but this is not a network identity proof (proxies and mutable indexes can
    change what they serve). The chunker and SHA pins must be approved by the
    operator independently, not computed from whichever index responds.
    """
    if type(base_url) is not str or not base_url.startswith(("http://", "https://")):
        raise ValueError("Qdrant base URL is required")
    if type(collection) is not str or not collection or collection != collection.strip():
        raise ValueError("one normalized Qdrant collection is required")
    if not callable(chunker) or not callable(embed_hybrid):
        raise ValueError("chunker and hybrid encoder are required")
    snapshot = load_pinned_document_snapshot(
        source_path, expected_sha256=expected_source_sha256,
    )
    expected_chunks = [
        chunk for document in snapshot.documents.values() for chunk in chunker(document)
    ]
    if not expected_chunks:
        raise ValueError("canonical source produced no chunks")
    audit_client = QdrantAuditRestClient(base_url)
    query_client = QdrantRestClient(base_url)
    session = AuditedIndexSession(
        audit_client, collection, expected_chunks,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    repository = QdrantChunkRepository(
        query_client, collection=collection, embed=_dense_only_disabled,
        embed_hybrid=embed_hybrid,
    )
    source = CanonicalHybridCandidates(
        repository, source_path, expected_sha256=expected_source_sha256,
    )
    # The repository has already compared each RAW query point (ID + payload)
    # to its decoded Chunk. Bind that decoded point to the SAME manifest used
    # by the audit, with JSON equality that distinguishes bool from int.
    manifest_points: dict[str, str] = {}
    for chunk in session.canonical_chunks:
        point = chunk_to_point(chunk, [1.0])
        if point["id"] in manifest_points:
            raise ValueError("duplicate point in canonical manifest")
        manifest_points[point["id"]] = json.dumps(
            point["payload"], sort_keys=True, allow_nan=False,
        )

    def require_manifest_member(candidate: HybridCandidate) -> None:
        point = chunk_to_point(candidate.chunk, [1.0])
        payload = json.dumps(point["payload"], sort_keys=True, allow_nan=False)
        if manifest_points.get(point["id"]) != payload:
            raise CanonicalAclError("observed candidate is not in audited manifest")

    stage = RerankedCandidateSource(
        source, reranker, tokenizer, candidate_limit=candidate_limit,
        top_k=top_k, max_length=max_length, batch_size=batch_size,
        candidate_guard=require_manifest_member,
    )
    opening = session.open()
    try:
        candidates = stage.candidates(question, context=context)
        closing = session.close()
    except BaseException:
        # No second scroll on an abort or Ctrl-C; no partial window escapes.
        session.invalidate()
        raise
    return AuditedCandidateWindow(tuple(candidates), opening, closing)
