"""One-shot G1 window bracketed by two Qdrant payload audits.

Two public entry points share one private engine: `run_audited_g1_candidate_window`
releases reranked candidates only, and `run_audited_g1_answer` additionally runs a
pilot cited-answer generation INSIDE the audited window (between the reranking and
the closing audit). Neither is a calibrated G1 receipt.

Neither audit freezes writes, checks vectors, or proves the query saw the same
snapshot. An empty candidate window is NOT an honest abstention verdict.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import json
from pathlib import Path

from .acl import AuthorizationContext, Chunk
from .canonical_snapshot import load_pinned_document_snapshot
from .g1_hybrid_candidates import CanonicalHybridCandidates
from .g1_reranking import RerankedCandidate, RerankedCandidateSource
from .index_integrity import AuditedIndexSession, IndexSnapshotReport
from .ingestion import Document
from .qdrant_repository import HybridCandidate, QdrantChunkRepository
from .qdrant_identity import validate_audit_tokens
from .qdrant_rest import QdrantAuditClient, QdrantRestClient
from .qdrant_store import chunk_to_point
from .redacted_repr import REDACTED, safe_count, safe_length
from .retrieval import CanonicalAclError
from .answering import AnswerTrace, answer_from_evidence
from .generator import GenerationError


def _audited_points(report: object) -> str:
    """Render an audit report's point count even when the report is forged.

    The exact type is checked before the attribute is read, and the attribute
    is read defensively: `object.__new__(IndexSnapshotReport)` passes the type
    check with no field set at all.
    """
    if type(report) is not IndexSnapshotReport:
        return REDACTED
    return safe_count(getattr(report, "point_count", None))


@dataclass(frozen=True)
class AuditedCandidateWindow:
    """Uncalibrated candidates, plus the two completed payload audit reports."""

    candidates: tuple[RerankedCandidate, ...]
    opening: IndexSnapshotReport
    closing: IndexSnapshotReport

    def __repr__(self) -> str:
        # Same representation policy as `AuditedG1Answer` and the divergence
        # plans, including their shared redaction helper: this window carries
        # the SAME authorized passages as the answer path, so an accidental
        # repr (log line, f-string, traceback) must not copy their text,
        # offsets or source digests. Every field is type-checked before being
        # interpolated, because this public dataclass can be rebuilt with
        # forged fields. Masking the repr is NOT a security boundary: the raw
        # attributes stay readable, and the elements keep their own revealing
        # reprs.
        return (
            "AuditedCandidateWindow("
            f"candidates={safe_length(getattr(self, 'candidates', None))}, "
            f"opening_points={_audited_points(getattr(self, 'opening', None))}, "
            f"closing_points={_audited_points(getattr(self, 'closing', None))})"
        )


@dataclass(frozen=True)
class AuditedG1Answer:
    """Pilot answer with structural citations; NOT a calibrated G1 receipt.

    `candidates` keeps the reranked window that produced the answer so a future
    receipt can reconstruct it. Like `AuditedCandidateWindow`, this dataclass is
    NOT an attestation: `object.__new__`, `dataclasses.replace`, `pickle` and
    `deepcopy` all rebuild it with arbitrary fields next to authentic-looking
    audit reports. Do not accept it as proof in a receipt without an
    independently recomputable digest over the trace and the manifest.
    """

    trace: AnswerTrace
    candidates: tuple[RerankedCandidate, ...]
    opening: IndexSnapshotReport
    closing: IndexSnapshotReport

    def __repr__(self) -> str:
        # Same representation policy as the divergence plans: an accidental
        # repr (log line, traceback) must not copy evidence or citation text.
        # The raw attributes stay available for controlled programmatic use.
        # Each field is type-checked before interpolation: this dataclass is
        # rebuildable with forged fields (see the class docstring), and a
        # hostile counter's `__format__` would otherwise print anything or
        # raise while a traceback is being formatted.
        trace = getattr(self, "trace", None)
        response = getattr(trace, "response", None) if type(trace) is AnswerTrace else None
        abstained = getattr(response, "abstained", None)
        return (
            "AuditedG1Answer("
            f"abstained={abstained if type(abstained) is bool else REDACTED}, "
            f"citations={safe_length(getattr(response, 'citations', None))}, "
            f"candidates={safe_length(getattr(self, 'candidates', None))}, "
            f"opening_points={_audited_points(getattr(self, 'opening', None))}, "
            f"closing_points={_audited_points(getattr(self, 'closing', None))})"
        )


def _dense_only_disabled(_query: str) -> list[float]:
    raise ValueError("the audited G1 window requires a hybrid encoder")


def _run_audited_g1_window(
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
    audit_api_key: str = "",
    query_api_key: str = "",
    candidate_limit: int = 20,
    top_k: int = 8,
    max_length: int = 512,
    batch_size: int = 1,
    answer_fn: Callable[[tuple[RerankedCandidate, ...]], AnswerTrace] | None = None,
) -> tuple[
    tuple[RerankedCandidate, ...], AnswerTrace | None,
    IndexSnapshotReport, IndexSnapshotReport,
]:
    """Shared engine of the two public entry points. PRIVATE on purpose.

    An answer callback on a PUBLIC signature would let any caller obtain both
    genuine audit reports around a fabricated answer while bypassing the
    pilot's own guards; each public wrapper below owns its guards and returns a
    single type.

    Order: schema preflight, opening audit, hybrid query, canonical barrier,
    manifest guard, reranking, THEN `answer_fn` when supplied, THEN the closing
    audit. The callback therefore sees the window BEFORE the closing audit has
    confirmed the index: nothing is released to the caller when that audit
    fails, but an injected generator will already have seen those passages.

    The two clients are constructed here from the SAME base URL and collection,
    but this is not a network identity proof (proxies and mutable indexes can
    change what they serve). The chunker and SHA pins must be approved by the
    operator independently, not computed from whichever index responds.

    The audit reader and the query client carry SEPARATE read-only credentials
    (`audit_api_key`, `query_api_key`): neither role writes, and keeping them
    distinct makes audit reads separable from user traffic server-side. Both
    may be empty only against an unauthenticated development instance.
    """
    if type(base_url) is not str or not base_url.startswith(("http://", "https://")):
        raise ValueError("Qdrant base URL is required")
    if type(collection) is not str or not collection or collection != collection.strip():
        raise ValueError("one normalized Qdrant collection is required")
    if not callable(chunker) or not callable(embed_hybrid):
        raise ValueError("chunker and hybrid encoder are required")
    validate_audit_tokens(
        audit_key=audit_api_key, query_key=query_api_key, collection=collection
    )
    snapshot = load_pinned_document_snapshot(
        source_path, expected_sha256=expected_source_sha256,
    )
    expected_chunks = [
        chunk for document in snapshot.documents.values() for chunk in chunker(document)
    ]
    if not expected_chunks:
        raise ValueError("canonical source produced no chunks")
    # The audit reader holds only a transport: no mutation method exists in its
    # object graph, and its credential is read-only on this collection.
    audit_client = QdrantAuditClient(base_url, api_key=audit_api_key)
    query_client = QdrantRestClient(base_url, api_key=query_api_key)
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

    def require_manifest_member(candidate: HybridCandidate | RerankedCandidate) -> None:
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
        trace = answer_fn(tuple(candidates)) if answer_fn is not None else None
        if trace is not None:
            if type(trace) is not AnswerTrace:
                raise GenerationError("audited G1 answer path produced no answer trace")
            # The generator can retain and mutate its Chunk objects even AFTER
            # this check, while the closing scroll is in flight. Snapshot every
            # published candidate into a private object, bind BOTH the original
            # and the copy to the pinned manifest, and rebuild the trace from
            # those copies. This never calls the generator a second time.
            published = []
            for candidate in candidates:
                require_manifest_member(candidate)
                copy = replace(candidate, chunk=replace(candidate.chunk))
                require_manifest_member(copy)
                published.append(copy)
            candidates = published
            answer_text = trace.response.answer
            trace = answer_from_evidence(
                question, tuple(candidate.chunk for candidate in candidates),
                generator=lambda _question, _evidence: answer_text,
                strict_citations=True,
            )
        closing = session.close()
    except BaseException:
        # No second scroll on an abort or Ctrl-C, and no partial window escapes
        # to the CALLER (an `answer_fn` may already have seen it). The session
        # stays terminal: no retry can bless a later window with this audit.
        session.invalidate()
        raise
    return tuple(candidates), trace, opening, closing


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
    audit_api_key: str = "",
    query_api_key: str = "",
    candidate_limit: int = 20,
    top_k: int = 8,
    max_length: int = 512,
    batch_size: int = 1,
) -> AuditedCandidateWindow:
    """Audit, retrieve and rerank, audit again, *then* release candidates.

    No answer, no citation and no abstention verdict: an empty window only
    means "no usable candidate in this bounded window".
    """
    candidates, _trace, opening, closing = _run_audited_g1_window(
        base_url=base_url, collection=collection, source_path=source_path,
        expected_source_sha256=expected_source_sha256,
        expected_manifest_sha256=expected_manifest_sha256, chunker=chunker,
        embed_hybrid=embed_hybrid, reranker=reranker, tokenizer=tokenizer,
        question=question, context=context, audit_api_key=audit_api_key,
        query_api_key=query_api_key, candidate_limit=candidate_limit,
        top_k=top_k, max_length=max_length, batch_size=batch_size,
    )
    return AuditedCandidateWindow(candidates, opening, closing)


def run_audited_g1_answer(
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
    generator: Callable[[str, tuple[Chunk, ...]], str],
    audit_api_key: str = "",
    query_api_key: str = "",
    candidate_limit: int = 20,
    top_k: int = 8,
    max_length: int = 512,
    batch_size: int = 1,
) -> AuditedG1Answer:
    """CPU pilot: audit → canonical rerank → cited answer → closing audit.

    Never interpret an empty bounded candidate window as honest abstention.
    The generator's own abstention is not calibrated against a no-answer set.
    The generator runs BEFORE the closing audit, so it sees the passages even
    when that audit later refuses to release the answer.
    """
    if not callable(generator):
        raise ValueError("G1 answer generator must be callable")

    def answer(candidates: tuple[RerankedCandidate, ...]) -> AnswerTrace:
        return answer_from_evidence(
            question, tuple(candidate.chunk for candidate in candidates),
            generator=generator, strict_citations=True,
        )

    candidates, trace, opening, closing = _run_audited_g1_window(
        base_url=base_url, collection=collection, source_path=source_path,
        expected_source_sha256=expected_source_sha256,
        expected_manifest_sha256=expected_manifest_sha256, chunker=chunker,
        embed_hybrid=embed_hybrid, reranker=reranker, tokenizer=tokenizer,
        question=question, context=context, audit_api_key=audit_api_key,
        query_api_key=query_api_key, candidate_limit=candidate_limit, top_k=top_k,
        max_length=max_length, batch_size=batch_size, answer_fn=answer,
    )
    if type(trace) is not AnswerTrace:
        # Fail closed rather than assert: an `assert` disappears under
        # `python -O` and would let a non-answer escape typed as one.
        raise GenerationError("audited G1 answer path produced no answer trace")
    return AuditedG1Answer(trace, candidates, opening, closing)
