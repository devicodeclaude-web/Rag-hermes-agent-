from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Literal


@dataclass(frozen=True)
class CitationJudgment:
    claim_id: str
    chunk_id: str
    is_valid: bool
    supports_claim: bool


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    relevant_chunk_ids: tuple[str, ...]
    retrieved_chunk_ids: tuple[str, ...]
    cited_chunk_ids: tuple[str, ...]
    should_abstain: bool
    did_abstain: bool
    leaked_chunk_ids: tuple[str, ...]
    technical_failure: Literal["acl_error", "backend_error", "token_budget_error"] | None = None
    citation_judgments: tuple[CitationJudgment, ...] | None = None


@dataclass(frozen=True)
class EvaluationReport:
    case_count: int
    recall_at_k: float
    mrr: float
    citation_precision: float
    citation_validity_precision: float | None
    citation_support_precision: float | None
    abstention_precision: float
    abstention_recall: float
    leak_count: int
    security_gate_passed: bool
    acl_error_count: int
    backend_error_count: int
    token_budget_error_count: int


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def evaluate(cases: Iterable[EvaluationCase], k: int) -> EvaluationReport:
    items = list(cases)
    if not items:
        raise ValueError("at least one evaluation case is required")
    if k < 1:
        raise ValueError("k must be positive")
    allowed_failures = {None, "acl_error", "backend_error", "token_budget_error"}
    if any(case.technical_failure not in allowed_failures for case in items):
        raise ValueError("unknown technical failure status")
    if any(case.technical_failure and case.did_abstain for case in items):
        raise ValueError("a technical failure cannot be recorded as an abstention")

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

    citation_eligible_cases = [case for case in items if case.technical_failure is None]
    all_citations = [
        chunk_id for case in citation_eligible_cases for chunk_id in case.cited_chunk_ids
    ]
    legacy_supported_citations = sum(
        chunk_id in set(case.relevant_chunk_ids)
        for case in citation_eligible_cases
        for chunk_id in case.cited_chunk_ids
    )
    citation_cases = [case for case in citation_eligible_cases if case.cited_chunk_ids]
    strict_citations_available = all(
        case.citation_judgments is not None
        and Counter(judgment.chunk_id for judgment in case.citation_judgments)
        == Counter(case.cited_chunk_ids)
        for case in citation_cases
    )
    citation_judgments = [
        judgment
        for case in citation_cases
        for judgment in (case.citation_judgments or ())
    ]

    true_positive_abstentions = sum(
        case.should_abstain and case.did_abstain for case in items
    )
    predicted_abstentions = sum(case.did_abstain for case in items)
    required_abstentions = sum(case.should_abstain for case in items)
    leak_count = sum(len(case.leaked_chunk_ids) for case in items)
    acl_error_count = sum(case.technical_failure == "acl_error" for case in items)
    backend_error_count = sum(
        case.technical_failure == "backend_error" for case in items
    )
    token_budget_error_count = sum(
        case.technical_failure == "token_budget_error" for case in items
    )

    return EvaluationReport(
        case_count=len(items),
        recall_at_k=_safe_ratio(sum(recalls), len(recalls)),
        mrr=_safe_ratio(sum(reciprocal_ranks), len(reciprocal_ranks)),
        citation_precision=_safe_ratio(legacy_supported_citations, len(all_citations)),
        citation_validity_precision=(
            _safe_ratio(
                sum(judgment.is_valid for judgment in citation_judgments),
                len(citation_judgments),
            )
            if strict_citations_available
            else None
        ),
        citation_support_precision=(
            _safe_ratio(
                sum(
                    judgment.is_valid and judgment.supports_claim
                    for judgment in citation_judgments
                ),
                len(citation_judgments),
            )
            if strict_citations_available
            else None
        ),
        abstention_precision=_safe_ratio(true_positive_abstentions, predicted_abstentions),
        abstention_recall=_safe_ratio(true_positive_abstentions, required_abstentions),
        leak_count=leak_count,
        security_gate_passed=leak_count == 0,
        acl_error_count=acl_error_count,
        backend_error_count=backend_error_count,
        token_budget_error_count=token_budget_error_count,
    )
