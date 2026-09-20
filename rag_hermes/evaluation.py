from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    relevant_chunk_ids: tuple[str, ...]
    retrieved_chunk_ids: tuple[str, ...]
    cited_chunk_ids: tuple[str, ...]
    should_abstain: bool
    did_abstain: bool
    leaked_chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationReport:
    case_count: int
    recall_at_k: float
    mrr: float
    citation_precision: float
    abstention_precision: float
    abstention_recall: float
    leak_count: int
    security_gate_passed: bool


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def evaluate(cases: Iterable[EvaluationCase], k: int) -> EvaluationReport:
    items = list(cases)
    if not items:
        raise ValueError("at least one evaluation case is required")
    if k < 1:
        raise ValueError("k must be positive")

    answerable = [case for case in items if case.relevant_chunk_ids]
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    for case in answerable:
        relevant = set(case.relevant_chunk_ids)
        top_k = case.retrieved_chunk_ids[:k]
        recalls.append(_safe_ratio(len(relevant.intersection(top_k)), len(relevant)))
        rank = next(
            (index for index, chunk_id in enumerate(case.retrieved_chunk_ids, 1) if chunk_id in relevant),
            None,
        )
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)

    all_citations = [chunk_id for case in items for chunk_id in case.cited_chunk_ids]
    supported_citations = sum(
        chunk_id in set(case.relevant_chunk_ids)
        for case in items
        for chunk_id in case.cited_chunk_ids
    )

    true_positive_abstentions = sum(
        case.should_abstain and case.did_abstain for case in items
    )
    predicted_abstentions = sum(case.did_abstain for case in items)
    required_abstentions = sum(case.should_abstain for case in items)
    leak_count = sum(len(case.leaked_chunk_ids) for case in items)

    return EvaluationReport(
        case_count=len(items),
        recall_at_k=_safe_ratio(sum(recalls), len(recalls)),
        mrr=_safe_ratio(sum(reciprocal_ranks), len(reciprocal_ranks)),
        citation_precision=_safe_ratio(supported_citations, len(all_citations)),
        abstention_precision=_safe_ratio(true_positive_abstentions, predicted_abstentions),
        abstention_recall=_safe_ratio(true_positive_abstentions, required_abstentions),
        leak_count=leak_count,
        security_gate_passed=leak_count == 0,
    )
