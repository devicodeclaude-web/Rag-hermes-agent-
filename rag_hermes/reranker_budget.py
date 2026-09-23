from __future__ import annotations


class RerankerBudgetExceeded(ValueError):
    pass


def count_pair_tokens(tokenizer, query: str, passage: str) -> int:
    encoded = tokenizer(
        query,
        passage,
        add_special_tokens=True,
        truncation=False,
    )
    return len(encoded["input_ids"])


def assert_pair_fits(tokenizer, query: str, passage: str, *, max_length: int = 512) -> int:
    if max_length < 1:
        raise ValueError("max_length must be positive")
    token_count = count_pair_tokens(tokenizer, query, passage)
    if token_count > max_length:
        raise RerankerBudgetExceeded(
            f"reranker pair has {token_count} tokens, exceeding max_length {max_length}"
        )
    return token_count
