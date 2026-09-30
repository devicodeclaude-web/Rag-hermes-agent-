from __future__ import annotations

from typing import Any

from .acl import Chunk
from .reranker_budget import assert_pair_fits


class BudgetedCrossEncoderReranker:
    """Service-level reranker over already-authorized chunks.

    Wraps a cross-encoder (e.g. BGE-reranker-v2-m3 via FlagEmbedding) and the
    exact tokenizer. Every (question, passage) pair is checked against the
    512-token budget with the real tokenizer BEFORE scoring; an over-budget
    pair is rejected (never truncated) and the model is never called. The model
    itself is injected, so this module never downloads or selects weights
    implicitly — the pinned checkpoint is wired in explicitly at the call site.
    """

    def __init__(
        self,
        *,
        model: Any,
        tokenizer: Any,
        max_length: int = 512,
        batch_size: int = 8,
    ) -> None:
        if max_length < 1:
            raise ValueError("max_length must be positive")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._model = model
        self._tokenizer = tokenizer
        self._max_length = max_length
        self._batch_size = batch_size

    def __call__(self, question: str, chunks: tuple[Chunk, ...]) -> list[float]:
        if not chunks:
            return []
        pairs: list[list[str]] = []
        for chunk in chunks:
            # Fail closed on the exact token budget before any scoring.
            assert_pair_fits(
                self._tokenizer, question, chunk.text, max_length=self._max_length
            )
            pairs.append([question, chunk.text])
        raw = self._model.compute_score(
            pairs,
            batch_size=self._batch_size,
            max_length=self._max_length,
            normalize=True,
        )
        scores = [float(raw)] if isinstance(raw, (int, float)) else [float(x) for x in raw]
        if len(scores) != len(chunks):
            raise ValueError("cross-encoder returned a wrong number of scores")
        return scores
