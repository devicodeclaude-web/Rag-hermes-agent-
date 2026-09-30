"""Migrate legacy v1 benchmark rows into canonical synthetic evaluation cases.

The v1 dataset (data/benchmark/dataset-v1.jsonl) holds machine-generated
questions labelled at DOCUMENT granularity (relevant_document_ids), not passage
spans. This module converts each v1 row into a case that satisfies the strict
canonical schema (rag_hermes.evaluation_dataset.validate_evaluation_case) while
recording two honest facts:

  1. Provenance is SYNTHETIC_PROVENANCE — the question was generated from the
     corpus, so is_quality_eligible() is False and it can never inflate a
     human-grade quality score (non-circularity preserved).
  2. Relevance is coarse: each relevant document becomes a FULL-DOCUMENT span
     (start=0, end=len(content)). This is honest but document-level; it is not a
     passage-precise label. Recorded so downstream metrics are read as recall@k
     at document granularity, never as fine-grained passage relevance.

reference_status stays "pending": nothing here is human-reviewed, and the v2
readiness gate must never treat these as validated.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .evaluation_dataset import SYNTHETIC_PROVENANCE, validate_evaluation_case

# Legacy category that marks an intentionally unanswerable (abstention) case.
_NO_ANSWER_CATEGORY = "no_answer"


def _full_document_span(
    document_id: str, documents: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    if document_id not in documents:
        raise ValueError(f"unknown relevant document_id: {document_id}")
    content = str(documents[document_id]["content"])
    return {
        "document_id": document_id,
        "start_char": 0,
        "end_char": len(content),
        "passage_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "relevance_grade": 2,
    }


def build_synthetic_case(
    raw: Mapping[str, Any],
    documents: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a canonical, strictly-validated synthetic case from a v1 row.

    Answerable rows (non-empty relevant_document_ids) become full-document spans.
    ``no_answer`` rows (or rows with no relevant document) become abstention
    cases with a recorded unanswerable_reason. The result is validated against
    the canonical schema before it is returned, so a malformed row fails closed.
    """
    category = str(raw.get("category", ""))
    relevant_ids = list(raw.get("relevant_document_ids", []))
    is_abstention = category == _NO_ANSWER_CATEGORY

    # Guard against an incoherent legacy row: an explicit no_answer must not
    # carry relevant documents, and an answerable category must carry at least
    # one relevant document (otherwise the label is silently lost).
    if is_abstention and relevant_ids:
        raise ValueError(
            f"{raw.get('case_id')!r}: no_answer case cannot list relevant documents"
        )
    if not is_abstention and not relevant_ids:
        raise ValueError(
            f"{raw.get('case_id')!r}: answerable category {category!r} has no "
            "relevant_document_ids"
        )

    if is_abstention:
        spans: list[dict[str, Any]] = []
        should_abstain = True
        unanswerable_reason = "generated_no_answer_case_not_supported_by_corpus"
    else:
        spans = [_full_document_span(doc_id, documents) for doc_id in relevant_ids]
        should_abstain = False
        unanswerable_reason = None

    case: dict[str, Any] = {
        "case_id": str(raw["case_id"]),
        "question": str(raw["question"]),
        "language": "en",
        "track": "en2en",
        "category": category,
        "access_scope": "public",
        "question_provenance": SYNTHETIC_PROVENANCE,
        "should_abstain": should_abstain,
        "unanswerable_reason": unanswerable_reason,
        "reference_status": "pending",
        "source_revision": manifest["source_revision"],
        "corpus_manifest_sha": manifest["corpus_manifest_sha"],
        "relevance_spans": spans,
    }
    # Fail closed: the row must satisfy the canonical strict schema.
    validate_evaluation_case(case, documents, manifest)
    return case
