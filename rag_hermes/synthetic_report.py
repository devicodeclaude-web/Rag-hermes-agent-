"""Run the synthetic evaluation track through the real RagService answer path.

This produces a document-granularity retrieval report (recall@k, MRR, abstention,
leak) for the synthetic track. The report is a TECHNICAL WITNESS only: the
synthetic questions are corpus-generated (is_quality_eligible == False) and the
relevance labels are whole-document spans, so the numbers measure document-level
retrieval, never human-grade answer quality.

Every case is still validated against the strict canonical schema (inside
run_evaluation) before any answer runs, so a stale corpus hash aborts the report.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .acl import AuthorizationContext
from .evaluation import EvaluationReport
from .evaluation_runner import build_service_answer_fn, run_evaluation
from .ingestion import Document
from .service import RagService

_PUBLIC_TENANT = "public"


def _evaluator_context() -> AuthorizationContext:
    return AuthorizationContext(
        tenant_id=_PUBLIC_TENANT,
        user_id="evaluator",
        groups=(),
        clearance=0,
    )


def build_public_service(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    minimum_score: float = 0.2,
    top_k: int = 1,
    retrieval_k: int | None = None,
    reranker: Any | None = None,
) -> RagService:
    """Ingest every public document into an in-memory RagService.

    Documents are ingested under the public tenant so the evaluator context can
    retrieve them. Non-public documents are skipped: the synthetic track is
    public-only, and ingesting a private document under a public owner would be a
    silent ACL widening.
    """
    service = RagService(
        minimum_score=minimum_score,
        top_k=top_k,
        retrieval_k=retrieval_k,
        reranker=reranker,
    )
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
                source_uri=f"synthetic://{document_id}",
            ),
            context=context,
        )
    return service


def run_synthetic_evaluation(
    cases: Sequence[Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
    *,
    k: int,
    minimum_score: float = 0.2,
    retrieval_k: int | None = None,
    reranker: Any | None = None,
) -> EvaluationReport:
    """Build a public service, then score the synthetic cases through it."""
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")

    service = build_public_service(
        documents,
        minimum_score=minimum_score,
        top_k=k,
        retrieval_k=retrieval_k,
        reranker=reranker,
    )
    context = _evaluator_context()

    def context_for_case(_case: Mapping[str, Any]) -> AuthorizationContext:
        return context

    answer_fn = build_service_answer_fn(service, context_for_case)
    return run_evaluation(cases, documents, manifest, answer_fn, k=k)
