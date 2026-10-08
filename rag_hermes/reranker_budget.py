from __future__ import annotations

from dataclasses import dataclass


class RerankerBudgetExceeded(ValueError):
    """Levée quand aucune paire candidate ne tient dans le budget de tokens.

    Au niveau requête, elle correspond au statut ERROR_TOKEN_BUDGET : jamais une
    abstention, jamais retirée du dénominateur.
    """


@dataclass(frozen=True)
class RejectedPair:
    """Trace typée d'une paire question+passage écartée pour dépassement."""

    index: int
    document_id: str
    token_count: int
    max_length: int
    reason: str = "token_budget"


def count_pair_tokens(tokenizer, query: str, passage: str) -> int:
    """Unique source de vérité du budget : compte question + passage + tokens
    spéciaux avec le tokenizer du reranker. Jamais de troncature."""
    encoded = tokenizer(
        query,
        passage,
        add_special_tokens=True,
        truncation=False,
    )
    return len(encoded["input_ids"])


def pair_fits(tokenizer, query: str, passage: str, *, max_length: int = 512) -> tuple[bool, int]:
    """Retourne (tient, nombre_de_tokens). Sans `assert` : la garde survit au
    mode optimisé (`python -O`)."""
    if max_length < 1:
        raise ValueError("max_length must be positive")
    token_count = count_pair_tokens(tokenizer, query, passage)
    return token_count <= max_length, token_count


def assert_pair_fits(tokenizer, query: str, passage: str, *, max_length: int = 512) -> int:
    """Garde pour une paire unique : lève si hors budget, sinon rend le compte."""
    fits, token_count = pair_fits(tokenizer, query, passage, max_length=max_length)
    if not fits:
        raise RerankerBudgetExceeded(
            f"reranker pair has {token_count} tokens, exceeding max_length {max_length}"
        )
    return token_count


def passage_token_budget(
    *, reranker_max_length: int, question_token_margin: int, special_token_reserve: int
) -> int:
    """Budget de passage à l'ingestion, dérivé du budget du reranker.

    `question_token_margin` est la marge de tokens NOMMÉE réservée à la question ;
    `special_token_reserve` couvre les tokens spéciaux ajoutés par le tokenizer.
    Garantit, par construction, que passage + question + spéciaux <= budget.
    """
    if min(reranker_max_length, question_token_margin, special_token_reserve) < 0:
        raise ValueError("budget components must be non-negative")
    budget = reranker_max_length - question_token_margin - special_token_reserve
    if budget < 1:
        raise ValueError(
            "no room left for the passage: "
            f"{reranker_max_length} - {question_token_margin} - {special_token_reserve} <= 0"
        )
    return budget
