"""Offline comparison harness: RAG vs closed-book on the same questions.

The generative campaign must contrast the RAG answer path with the mandatory
no-retrieval baseline (rule 7). What is scorable OFFLINE is the abstention axis on
both sides. What is NOT scorable offline is answer correctness — that is exactly
what the >=20% human review judges. So this harness:

  - measures abstention recall/precision for BOTH campaigns;
  - builds a deterministic review sample pairing, per case, the RAG answer and
    the closed-book answer, so a human can decide which (if any) is correct.

Both campaigns are driven through injected `answer_fn(question) -> str`
callables, so this module never makes a network call and stays fully offline.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Callable, Mapping, Sequence

from .closed_book import CLOSED_BOOK_ABSTENTION

AnswerFn = Callable[[str], str]

# RAG and closed-book use different abstention strings; a campaign is considered
# to have abstained when its answer equals ITS OWN abstention sentinel.
from .generator import ABSTENTION_ANSWER as _RAG_ABSTENTION


def _did_abstain(answer: str, sentinel: str) -> bool:
    return answer.strip() == sentinel


@dataclass(frozen=True)
class ComparisonPair:
    case_id: str
    question: str
    should_abstain: bool
    rag_answer: str
    closed_book_answer: str


@dataclass(frozen=True)
class ComparisonResult:
    total: int
    rag_abstention_precision: float
    rag_abstention_recall: float
    closed_book_abstention_precision: float
    closed_book_abstention_recall: float
    review_sample: tuple[ComparisonPair, ...]


def _safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _validate_cases(cases: Sequence[Mapping[str, object]]) -> None:
    seen: set[str] = set()
    for case in cases:
        case_id = str(case["case_id"])
        if case_id in seen:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        if type(case["should_abstain"]) is not bool:
            raise ValueError(f"{case_id}: should_abstain must be a bool")


def build_review_sample(
    cases: Sequence[Mapping[str, object]],
    rag_answer: AnswerFn,
    closed_book_answer: AnswerFn,
    *,
    fraction: float,
    seed: int,
) -> list[ComparisonPair]:
    """Pair each sampled case's RAG and closed-book answers for human review.

    The sample is a deterministic (seed-fixed) subset of size ceil(fraction*N),
    with at least one case whenever there is any. fraction must be in ]0, 1].
    """
    if not (0.0 < fraction <= 1.0):
        raise ValueError("fraction must be in the interval (0, 1]")
    _validate_cases(cases)

    ordered = list(cases)
    sample_size = max(1, math.ceil(len(ordered) * fraction)) if ordered else 0
    rng = random.Random(seed)
    indices = sorted(rng.sample(range(len(ordered)), sample_size)) if ordered else []

    pairs: list[ComparisonPair] = []
    for index in indices:
        case = ordered[index]
        question = str(case["question"])
        pairs.append(
            ComparisonPair(
                case_id=str(case["case_id"]),
                question=question,
                should_abstain=bool(case["should_abstain"]),
                rag_answer=rag_answer(question),
                closed_book_answer=closed_book_answer(question),
            )
        )
    return pairs


def compare_campaigns(
    cases: Sequence[Mapping[str, object]],
    rag_answer: AnswerFn,
    closed_book_answer: AnswerFn,
    *,
    review_fraction: float,
    seed: int,
) -> ComparisonResult:
    """Score abstention for both campaigns and draw the human-review sample."""
    _validate_cases(cases)

    required = 0
    rag_pred = rag_tp = 0
    cb_pred = cb_tp = 0
    for case in cases:
        should_abstain = bool(case["should_abstain"])
        if should_abstain:
            required += 1
        question = str(case["question"])

        rag = rag_answer(question)
        if _did_abstain(rag, _RAG_ABSTENTION):
            rag_pred += 1
            if should_abstain:
                rag_tp += 1

        cb = closed_book_answer(question)
        if _did_abstain(cb, CLOSED_BOOK_ABSTENTION):
            cb_pred += 1
            if should_abstain:
                cb_tp += 1

    review_sample = build_review_sample(
        cases, rag_answer, closed_book_answer, fraction=review_fraction, seed=seed
    )

    return ComparisonResult(
        total=len(list(cases)),
        rag_abstention_precision=_safe_ratio(rag_tp, rag_pred),
        rag_abstention_recall=_safe_ratio(rag_tp, required),
        closed_book_abstention_precision=_safe_ratio(cb_tp, cb_pred),
        closed_book_abstention_recall=_safe_ratio(cb_tp, required),
        review_sample=tuple(review_sample),
    )
