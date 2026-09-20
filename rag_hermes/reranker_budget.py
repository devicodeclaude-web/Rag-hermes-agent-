from __future__ import annotations

from typing import Any


def assert_pair_fits(
    tokenizer: Any,
    query: str,
    passage: str,
    *,
    max_length: int = 512,
) -> int:
    if max_length < 1:
        raise ValueError("max_length must be positive")
    encoded = tokenizer(
        query,
        passage,
        add_special_tokens=True,
        truncation=False,
    )
    input_ids = encoded["input_ids"]
    token_count = len(input_ids)
    if token_count > max_length:
        raise ValueError(
            f"reranker pair has {token_count} tokens, exceeding max_length {max_length}"
        )
    return token_count
