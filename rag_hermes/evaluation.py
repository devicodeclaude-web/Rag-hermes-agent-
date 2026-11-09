from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Literal

TerminalStatus = Literal["answered", "abstained", "acl_error", "backend_error"]


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
    technical_failure: Literal["acl_error", "backend_error"] | None = None
    citation_judgments: tuple[CitationJudgment, ...] | None = None
    retrieved_relevance_ids_by_rank: tuple[tuple[str, ...], ...] | None = None

    def __post_init__(self) -> None:
        # Exclusivity is enforced HERE, not in evaluate(), so that no case can
        # exist whose `terminal_status` contradicts its own fields: the property
        # prioritises the failure and would otherwise silently hide the clash.
        if self.technical_failure not in {None, "acl_error", "backend_error"}:
            raise ValueError("unknown technical failure status")
        if self.technical_failure is not None and self.did_abstain:
            raise ValueError("a technical failure cannot be recorded as an abstention")

    @property
    def terminal_status(self) -> TerminalStatus:
        if self.technical_failure is not None:
            return self.technical_failure
        return "abstained" if self.did_abstain else "answered"


@dataclass(frozen=True)
class EvaluationReport:
    case_count: int
    recall_at_k: float
    mrr: float
    citation_precision: float
    citation_precision_lower_bound: float
    citation_validity_precision: float | None
    citation_validity_precision_lower_bound: float | None
    citation_support_precision: float | None
    citation_support_precision_lower_bound: float | None
    abstention_precision: float
    abstention_precision_lower_bound: float
    abstention_recall: float
    leak_count: int
    security_gate_passed: bool
    acl_error_count: int
    backend_error_count: int
    terminal_statuses: tuple[tuple[str, TerminalStatus], ...]
    terminal_status_source: Literal[
        "no_runtime_error_observed", "runtime_errors_observed"
    ]


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def evaluate(cases: Iterable[EvaluationCase], k: int) -> EvaluationReport:
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    items = list(cases)
    if not items:
        raise ValueError("at least one evaluation case is required")
    case_ids = [case.case_id for case in items]
    if any(type(case_id) is not str for case_id in case_ids):
        # Also protects the sort of terminal_statuses: mixed types would raise
        # an opaque TypeError instead of naming the offending contract.
        raise ValueError("case_id must be a string")
    if len(case_ids) != len(set(case_ids)):
        # Distinct wording from evaluation_runner.py's upstream guard, so a
        # failure says WHICH layer refused.
        raise ValueError("duplicate case_id in scored cases")
    # Defence in depth, NOT redundancy: EvaluationCase.__post_init__ enforces
    # exclusivity for every normal construction, but object.__new__,
    # copy.deepcopy and pickle all bypass it. Without this re-check a forged
    # case published a failure status while `terminal_status_source` still said
    # `no_runtime_error_observed`, and an unknown label escaped into
    # `terminal_statuses` outside the declared TerminalStatus literal.
    if any(
        case.technical_failure not in {None, "acl_error", "backend_error"}
        for case in items
    ):
        raise ValueError("unknown technical failure status reached the scorer")
    if any(case.technical_failure is not None and case.did_abstain for case in items):
        raise ValueError(
            "a technical failure cannot be recorded as an abstention (scorer re-check)"
        )
    for case in items:
        ranked = case.retrieved_relevance_ids_by_rank
        if ranked is None:
            continue
        if len(ranked) != len(case.retrieved_chunk_ids):
            raise ValueError("ranked relevance map length does not match retrievals")
        relevant = set(case.relevant_chunk_ids)
        for retrieved_id, labels in zip(case.retrieved_chunk_ids, ranked):
            if len(labels) != len(set(labels)):
                raise ValueError("ranked relevance map contains duplicate labels")
            if any(label not in relevant for label in labels):
                raise ValueError("ranked relevance map contains unknown labels")
            if labels and retrieved_id != labels[0]:
                raise ValueError("ranked relevance map does not match retrieved labels")

    answerable = [case for case in items if case.relevant_chunk_ids]
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    for case in answerable:
        relevant = set(case.relevant_chunk_ids)
        if case.retrieved_relevance_ids_by_rank is None:
            top_k = case.retrieved_chunk_ids[:k]
            covered = relevant.intersection(top_k)
            rank = next(
                (
                    index
                    for index, chunk_id in enumerate(case.retrieved_chunk_ids, 1)
                    if chunk_id in relevant
                ),
                None,
            )
        else:
            covered = relevant.intersection(
                label
                for labels in case.retrieved_relevance_ids_by_rank[:k]
                for label in labels
            )
            rank = next(
                (
                    index
                    for index, labels in enumerate(
                        case.retrieved_relevance_ids_by_rank, 1
                    )
                    if relevant.intersection(labels)
                ),
                None,
            )
        recalls.append(_safe_ratio(len(covered), len(relevant)))
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
    # Pessimistic bound (protocol v2 §6): every OBSERVED citation stays in the
    # denominator, including those of cases that ended in a technical failure,
    # and each of those is charged as unsupported. A case that failed before
    # emitting any citation records none, so the bound covers observed citations
    # only -- it is not a bound on citations the run never produced.
    observed_citation_count = sum(len(case.cited_chunk_ids) for case in items)
    failed_case_citation_count = observed_citation_count - len(all_citations)
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
    # Pessimistic bound (protocol v2 §6): a technical failure on a case that
    # should NOT abstain is charged as the false-positive abstention the system
    # avoided by crashing. A failure on a case that SHOULD abstain is never
    # charged -- its counterfactual is a true positive or a false negative,
    # neither of which inflates precision. No status is recoded as `abstained`.
    failures_charged_as_false_positives = sum(
        case.technical_failure is not None and not case.should_abstain
        for case in items
    )
    leak_count = sum(len(case.leaked_chunk_ids) for case in items)
    acl_error_count = sum(case.technical_failure == "acl_error" for case in items)
    backend_error_count = sum(
        case.technical_failure == "backend_error" for case in items
    )

    return EvaluationReport(
        case_count=len(items),
        recall_at_k=_safe_ratio(sum(recalls), len(recalls)),
        mrr=_safe_ratio(sum(reciprocal_ranks), len(reciprocal_ranks)),
        citation_precision=_safe_ratio(legacy_supported_citations, len(all_citations)),
        citation_precision_lower_bound=_safe_ratio(
            legacy_supported_citations, observed_citation_count
        ),
        citation_validity_precision=(
            _safe_ratio(
                sum(judgment.is_valid for judgment in citation_judgments),
                len(citation_judgments),
            )
            if strict_citations_available
            else None
        ),
        citation_validity_precision_lower_bound=(
            _safe_ratio(
                sum(judgment.is_valid for judgment in citation_judgments),
                len(citation_judgments) + failed_case_citation_count,
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
        citation_support_precision_lower_bound=(
            _safe_ratio(
                sum(
                    judgment.is_valid and judgment.supports_claim
                    for judgment in citation_judgments
                ),
                len(citation_judgments) + failed_case_citation_count,
            )
            if strict_citations_available
            else None
        ),
        abstention_precision=_safe_ratio(true_positive_abstentions, predicted_abstentions),
        abstention_precision_lower_bound=_safe_ratio(
            true_positive_abstentions,
            predicted_abstentions + failures_charged_as_false_positives,
        ),
        abstention_recall=_safe_ratio(true_positive_abstentions, required_abstentions),
        leak_count=leak_count,
        security_gate_passed=leak_count == 0,
        acl_error_count=acl_error_count,
        backend_error_count=backend_error_count,
        terminal_statuses=tuple(
            sorted((case.case_id, case.terminal_status) for case in items)
        ),
        # States what was OBSERVED, never that an error-reporting pipeline
        # exists: today run_evaluation sets no technical_failure at all.
        terminal_status_source=(
            "runtime_errors_observed"
            if acl_error_count or backend_error_count
            else "no_runtime_error_observed"
        ),
    )
