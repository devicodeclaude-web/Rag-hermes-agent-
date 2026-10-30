"""Aggregate human verdicts on the RAG-vs-closed-book review sample.

The comparison harness (campaign_compare) emits a review file where each pair
carries a human_verdict block {rag_correct, closed_book_correct, notes}. A human
fills rag_correct / closed_book_correct with true/false. This module turns those
verdicts into accuracy metrics — the ONLY measure of answer correctness, which no
offline metric can produce.

Fail-closed by default: if any pair is still unreviewed (a verdict left null),
aggregation refuses rather than publish partial accuracy. Pass
require_complete=False to compute over the reviewed subset only (for progress
checks), in which case denominators use the reviewed count.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ReviewAggregate:
    total: int
    reviewed: int
    rag_correct_count: int
    closed_book_correct_count: int
    rag_accuracy: float
    closed_book_accuracy: float
    rag_better_count: int
    closed_book_better_count: int


def _safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _verdict_bool(value: Any, field: str, case_id: str) -> bool | None:
    if value is None:
        return None
    if type(value) is not bool:
        raise ValueError(f"{case_id}: {field} must be a bool or null, got {value!r}")
    return value


def aggregate_review(
    pairs: Sequence[Mapping[str, Any]],
    *,
    require_complete: bool = True,
) -> ReviewAggregate:
    """Aggregate human verdicts into RAG vs closed-book accuracy."""
    if not pairs:
        raise ValueError("review sample is empty")

    seen: set[str] = set()
    reviewed = 0
    rag_correct = 0
    cb_correct = 0
    rag_better = 0
    cb_better = 0

    for pair in pairs:
        case_id = str(pair["case_id"])
        if case_id in seen:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen.add(case_id)

        if "human_verdict" not in pair:
            raise ValueError(f"{case_id}: missing human_verdict block")
        verdict = pair["human_verdict"]
        if not isinstance(verdict, dict):
            raise ValueError(f"{case_id}: human_verdict must be an object")

        rag_v = _verdict_bool(verdict.get("rag_correct"), "rag_correct", case_id)
        cb_v = _verdict_bool(
            verdict.get("closed_book_correct"), "closed_book_correct", case_id
        )

        if rag_v is None or cb_v is None:
            if require_complete:
                raise ValueError(
                    f"{case_id}: unreviewed verdict (rag_correct/closed_book_correct "
                    "must both be set); pass require_complete=False to allow partials"
                )
            # In partial mode an incomplete pair contributes nothing.
            if rag_v is None and cb_v is None:
                continue
            raise ValueError(
                f"{case_id}: a pair must be judged on BOTH campaigns or neither"
            )

        reviewed += 1
        rag_correct += 1 if rag_v else 0
        cb_correct += 1 if cb_v else 0
        if rag_v and not cb_v:
            rag_better += 1
        elif cb_v and not rag_v:
            cb_better += 1

    return ReviewAggregate(
        total=len(seen),
        reviewed=reviewed,
        rag_correct_count=rag_correct,
        closed_book_correct_count=cb_correct,
        rag_accuracy=_safe_ratio(rag_correct, reviewed),
        closed_book_accuracy=_safe_ratio(cb_correct, reviewed),
        rag_better_count=rag_better,
        closed_book_better_count=cb_better,
    )
