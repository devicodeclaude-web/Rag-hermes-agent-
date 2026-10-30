"""Consolidate retrieval, abstention and human-review campaign reports.

This module never promotes the synthetic track to quality evidence. It keeps the
three evidence classes separated and fails closed on inconsistent report sizes.
"""
from __future__ import annotations

from typing import Any, Mapping


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _integer(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a bool")
    return value


def build_campaign_summary(
    retrieval: Mapping[str, Any],
    comparison: Mapping[str, Any],
    human: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build one honest, structured summary from the three campaign reports."""
    if retrieval.get("track") != "synthetic" or comparison.get("track") != "synthetic":
        raise ValueError("campaign summary requires the synthetic track")
    if retrieval.get("quality_eligible") is not False:
        raise ValueError("quality-eligible input cannot enter the synthetic summary")

    retrieval_total = _integer(retrieval.get("cases_total"), "retrieval.cases_total")
    comparison_total = _integer(comparison.get("total"), "comparison.total")
    if retrieval_total != comparison_total:
        raise ValueError(
            f"case count mismatch: retrieval={retrieval_total}, "
            f"comparison={comparison_total}"
        )

    sample_size = _integer(
        comparison.get("review_sample_size"), "comparison.review_sample_size"
    )
    if sample_size > comparison_total:
        raise ValueError("review sample size exceeds campaign case count")

    metrics = _object(retrieval.get("metrics"), "retrieval.metrics")
    security_passed = _boolean(
        metrics.get("security_gate_passed"),
        "retrieval.metrics.security_gate_passed",
    )

    retrieval_section = {
        "status": "technical_witness_only",
        "cases_total": retrieval_total,
        "granularity": retrieval.get("granularity"),
        "retriever": retrieval.get("retriever"),
        "k": retrieval.get("k"),
        "recall_at_k": metrics.get("recall_at_k"),
        "mrr": metrics.get("mrr"),
        "citation_precision": metrics.get("citation_precision"),
        "leak_count": metrics.get("leak_count"),
        "security_gate_passed": security_passed,
    }
    abstention_section = {
        "status": "offline_comparison",
        "total": comparison_total,
        "review_fraction": comparison.get("review_fraction"),
        "review_sample_size": sample_size,
        "rag_abstention_precision": comparison.get("rag_abstention_precision"),
        "rag_abstention_recall": comparison.get("rag_abstention_recall"),
        "closed_book_abstention_precision": comparison.get(
            "closed_book_abstention_precision"
        ),
        "closed_book_abstention_recall": comparison.get(
            "closed_book_abstention_recall"
        ),
    }

    if human is None:
        human_section: dict[str, Any] = {
            "status": "missing",
            "expected_review_sample_size": sample_size,
        }
        campaign_status = "BLOCKED_human_review_missing"
    else:
        human_total = _integer(human.get("total"), "human.total")
        reviewed = _integer(human.get("reviewed"), "human.reviewed")
        complete = _boolean(human.get("complete_review"), "human.complete_review")
        if human_total != sample_size:
            raise ValueError(
                f"review sample size mismatch: comparison={sample_size}, "
                f"human={human_total}"
            )
        if reviewed > human_total:
            raise ValueError("human.reviewed exceeds human.total")
        if complete != (reviewed == human_total):
            raise ValueError(
                "complete human review requires reviewed == total, and partial "
                "review requires reviewed < total"
            )
        human_section = {
            "status": "complete" if complete else "partial",
            "total": human_total,
            "reviewed": reviewed,
            "rag_accuracy": human.get("rag_accuracy"),
            "closed_book_accuracy": human.get("closed_book_accuracy"),
            "rag_better_count": human.get("rag_better_count"),
            "closed_book_better_count": human.get("closed_book_better_count"),
        }
        campaign_status = (
            "COMPLETE_synthetic_technical_witness"
            if complete
            else "BLOCKED_human_review_incomplete"
        )

    if not security_passed:
        campaign_status = "FAILED_security_gate"

    return {
        "track": "synthetic",
        "status": campaign_status,
        "quality_evidence": False,
        "security_gate_passed": security_passed,
        "retrieval_technical": retrieval_section,
        "abstention_comparison": abstention_section,
        "human_correctness": human_section,
        "note": (
            "Synthetic technical witness only. Human correctness may complete "
            "this synthetic campaign, but never makes it quality evidence."
        ),
    }
