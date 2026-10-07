"""Human-authored evaluation track over the canonical public corpus.

This module is intentionally separate from the synthetic report. It accepts only
quality-eligible, reviewed cases and reports the in-memory lexical baseline
without claiming that the cross-lingual FR->EN track is comparable to EN->EN.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from .acl import AuthorizationContext
from .evaluation_dataset import is_quality_eligible
from .evaluation_runner import build_service_answer_fn, run_evaluation
from .ingestion import Document
from .service import RagService

_PUBLIC_TENANT = "public"
_REVIEWED_STATUSES = {"validated", "arbitrated"}


def _evaluator_context() -> AuthorizationContext:
    return AuthorizationContext(
        tenant_id=_PUBLIC_TENANT,
        user_id="evaluator",
        groups=(),
        clearance=0,
    )


def _build_public_service(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    minimum_score: float,
    top_k: int,
) -> RagService:
    service = RagService(minimum_score=minimum_score, top_k=top_k)
    context = _evaluator_context()
    for document_id, document in documents.items():
        if document.get("visibility") != "public":
            continue
        service.import_document(
            Document(
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
            ),
            context=context,
        )
    return service


def _counts(cases: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "cases_total": len(cases),
        "cases_answerable": sum(not case["should_abstain"] for case in cases),
        "cases_abstention": sum(case["should_abstain"] for case in cases),
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


def run_human_evaluation(
    cases: Sequence[Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
    *,
    k: int,
    minimum_score: float = 0.05,
) -> dict[str, Any]:
    """Score reviewed human cases globally and by track/category.

    EN->EN is the primary lexical baseline. FR->EN is emitted only as a
    cross-lingual diagnostic because raw lexical overlap is not an equitable
    baseline for French questions over an English corpus.
    """
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    if not cases:
        raise ValueError("at least one human evaluation case is required")
    if any(not is_quality_eligible(case) for case in cases):
        raise ValueError("human report accepts only quality-eligible cases")
    if any(case.get("reference_status") not in _REVIEWED_STATUSES for case in cases):
        raise ValueError("human report requires every reference to be reviewed")

    service = _build_public_service(
        documents,
        minimum_score=minimum_score,
        top_k=k,
    )
    context = _evaluator_context()
    answer_fn = build_service_answer_fn(service, lambda _case: context)

    overall = _score(cases, documents, manifest, answer_fn, k=k)
    by_track: dict[str, dict[str, Any]] = {}
    for track in sorted({str(case["track"]) for case in cases}):
        subset = [case for case in cases if case["track"] == track]
        result = _score(subset, documents, manifest, answer_fn, k=k)
        result["comparison_role"] = (
            "primary_lexical_baseline"
            if track == "en2en"
            else "cross_lingual_diagnostic_only"
        )
        by_track[track] = result

    by_category: dict[str, dict[str, Any]] = {}
    for category in sorted({str(case["category"]) for case in cases}):
        subset = [case for case in cases if case["category"] == category]
        by_category[category] = _score(
            subset, documents, manifest, answer_fn, k=k
        )

    return {
        "overall": overall,
        "by_track": by_track,
        "by_category": by_category,
    }
