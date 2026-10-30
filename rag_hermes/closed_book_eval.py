"""Evaluate the closed-book (no-retrieval) baseline on an abstention axis.

The baseline has no sources, so recall@k / citation metrics are meaningless. What
IS measurable offline is whether the model abstains honestly:
  - required_abstentions   : cases where should_abstain is True;
  - predicted_abstentions   : cases where the model returned the exact abstention;
  - true_positive_abstentions: cases that both should and did abstain.

Concrete answers (non-abstentions on answerable cases) are surfaced by case_id so
a human-review sample can be drawn from them — the mandatory ≥20% review of the
generative campaign judges those answers, which no offline metric can score.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .closed_book import CLOSED_BOOK_ABSTENTION, GenerationError

ClosedBookGeneratorFn = Callable[[str], str]


def _safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


@dataclass(frozen=True)
class ClosedBookReport:
    total: int
    required_abstentions: int
    predicted_abstentions: int
    true_positive_abstentions: int
    abstention_precision: float
    abstention_recall: float
    generation_failures: int
    answered_case_ids: tuple[str, ...]


def run_closed_book_evaluation(
    cases: Sequence[Mapping[str, object]],
    generator: ClosedBookGeneratorFn,
) -> ClosedBookReport:
    """Run each case's question through the closed-book generator and score."""
    seen: set[str] = set()
    required = 0
    predicted = 0
    true_positive = 0
    failures = 0
    answered: list[str] = []

    for case in cases:
        case_id = str(case["case_id"])
        if case_id in seen:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen.add(case_id)

        should_abstain = case["should_abstain"]
        if type(should_abstain) is not bool:
            raise ValueError(f"{case_id}: should_abstain must be a bool")
        if should_abstain:
            required += 1

        question = str(case["question"])
        try:
            answer = generator(question)
        except GenerationError:
            # A provider failure is neither an answer nor an abstention.
            failures += 1
            continue

        did_abstain = answer.strip() == CLOSED_BOOK_ABSTENTION
        if did_abstain:
            predicted += 1
            if should_abstain:
                true_positive += 1
        else:
            answered.append(case_id)

    return ClosedBookReport(
        total=len(seen),
        required_abstentions=required,
        predicted_abstentions=predicted,
        true_positive_abstentions=true_positive,
        abstention_precision=_safe_ratio(true_positive, predicted),
        abstention_recall=_safe_ratio(true_positive, required),
        generation_failures=failures,
        answered_case_ids=tuple(answered),
    )
