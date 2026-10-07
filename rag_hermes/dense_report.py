"""Dense persisted-retrieval evaluation track over the canonical public corpus.

This module exercises the real Qdrant-backed retrieval path (persisted vectors,
server-side ACL prefilter) while staying embedding-model agnostic. The embedder
is injected: a deterministic test vector locally (no semantic claim) or the
pinned BGE-M3 checkpoint during a GPU smoke. The emitted report therefore does
NOT claim semantic quality unless a real embedding model is used.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Mapping, Sequence

from .acl import AuthorizationContext
from .evaluation_dataset import is_quality_eligible
from .evaluation_runner import RetrievedChunk, run_evaluation
from .ingestion import Document, chunk_document

ContextFn = Callable[[Mapping[str, object]], AuthorizationContext]

_PUBLIC_TENANT = "public"
_REVIEWED_STATUSES = {"validated", "arbitrated"}


def build_qdrant_answer_fn(
    repository: Any,
    context_for_case: ContextFn,
    *,
    minimum_score: float,
    limit: int,
):
    """Adapt a Qdrant chunk repository's search path to the evaluation runner.

    The repository performs the real persisted dense search with its ACL
    prefilter. We apply the abstention/citation policy here, mirroring the
    lexical service: a candidate is citeable only when its score meets
    ``minimum_score``; if no candidate qualifies the system abstains. Retrieval
    still exposes every returned candidate so the runner can account for leaks.
    """

    def answer_fn(
        question: str,
        case: Mapping[str, object],
    ) -> tuple[Sequence[RetrievedChunk], Sequence[RetrievedChunk], bool]:
        context = context_for_case(case)
        if not isinstance(context, AuthorizationContext):
            raise ValueError("context_for_case must return AuthorizationContext")
        results = repository.search(question, context=context, limit=limit)
        retrieved = tuple(RetrievedChunk(result.chunk) for result in results)
        cited = tuple(
            RetrievedChunk(result.chunk)
            for result in results
            if result.score >= minimum_score
        )
        abstained = not cited
        return retrieved, cited, abstained

    return answer_fn


def _evaluator_context() -> AuthorizationContext:
    return AuthorizationContext(
        tenant_id=_PUBLIC_TENANT,
        user_id="evaluator",
        groups=(),
        clearance=0,
    )


def _document_from_mapping(document_id: str, document: Mapping[str, Any]) -> Document:
    return Document(
        document_id=document_id,
        content=str(document["content"]),
        tenant_id=_PUBLIC_TENANT,
        visibility="public",
        owner_id="evaluator",
        allowed_groups=(),
        allowed_users=(),
        classification=0,
        doc_version=1,
        source_uri=f"evaluation://{document_id}",
    )


def _ingest_public_corpus(
    repository: Any,
    documents: Mapping[str, Mapping[str, Any]],
) -> int:
    """Persist every public document's chunks into the Qdrant-backed store.

    Non-public documents are skipped: this track evaluates the public corpus
    only, mirroring the lexical human report's scope.
    """
    ingested = 0
    for document_id, document in documents.items():
        if document.get("visibility") != "public":
            continue
        model = _document_from_mapping(document_id, document)
        repository.replace_document(model, chunk_document(model))
        ingested += 1
    return ingested


def _counts(cases: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "cases_total": len(cases),
        "cases_answerable": sum(not case.get("should_abstain", False) for case in cases),
        "cases_abstention": sum(bool(case.get("should_abstain", False)) for case in cases),
    }


def _score(
    cases: Sequence[Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
    answer_fn,
    *,
    k: int,
) -> dict[str, Any]:
    report = run_evaluation(cases, documents, manifest, answer_fn, k=k)
    return {**_counts(cases), "metrics": asdict(report)}


def run_dense_evaluation(
    cases: Sequence[Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
    repository: Any,
    *,
    k: int,
    minimum_score: float = 0.05,
    limit: int | None = None,
) -> dict[str, Any]:
    """Score reviewed human cases through the persisted Qdrant dense retriever.

    The caller owns the repository (collection creation, embedder choice,
    teardown). We ingest the public corpus into it, then score every case with
    the same runner and reporting shape as the lexical human report, so the two
    reports are directly comparable. EN->EN is the primary track; FR->EN is a
    cross-lingual diagnostic.
    """
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    if not cases:
        raise ValueError("at least one dense evaluation case is required")
    if any(not is_quality_eligible(case) for case in cases):
        raise ValueError("dense report accepts only quality-eligible cases")
    if any(case.get("reference_status") not in _REVIEWED_STATUSES for case in cases):
        raise ValueError("dense report requires every reference to be reviewed")

    search_limit = k if limit is None else limit
    if type(search_limit) is not int or search_limit < 1:
        raise ValueError("limit must be a positive integer")

    _ingest_public_corpus(repository, documents)
    context = _evaluator_context()
    answer_fn = build_qdrant_answer_fn(
        repository,
        lambda _case: context,
        minimum_score=minimum_score,
        limit=search_limit,
    )

    overall = _score(cases, documents, manifest, answer_fn, k=k)
    by_track: dict[str, dict[str, Any]] = {}
    for track in sorted({str(case["track"]) for case in cases}):
        subset = [case for case in cases if case["track"] == track]
        result = _score(subset, documents, manifest, answer_fn, k=k)
        result["comparison_role"] = (
            "primary_dense_pipeline"
            if track == "en2en"
            else "cross_lingual_diagnostic_only"
        )
        by_track[track] = result

    by_category: dict[str, dict[str, Any]] = {}
    for category in sorted({str(case["category"]) for case in cases}):
        subset = [case for case in cases if case["category"] == category]
        by_category[category] = _score(subset, documents, manifest, answer_fn, k=k)

    return {
        "overall": overall,
        "by_track": by_track,
        "by_category": by_category,
    }
