"""Locked reranking over canonical candidates: reorder only, never authorize.

The reranker score is NOT a calibrated confidence: it must not be turned into
an abstention threshold here. This stage only reorders and truncates candidates
that the canonical ACL/provenance barrier already accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from itertools import islice
from numbers import Real
from typing import Any

from rag_hermes.acl import AuthorizationContext, Chunk
from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
from rag_hermes.reranker_budget import assert_pair_fits


@dataclass(frozen=True)
class RerankedCandidate:
    """Reranked candidate; `rerank_score` is uncalibrated, like `rrf_score`."""

    chunk: Chunk
    rerank_score: float
    rrf_score: float


class RerankedCandidateSource:
    """Score canonical candidates with an injected cross-encoder, then keep top_k.

    This class checks pair lengths, not the identity of the injected tokenizer
    or model. Checkpoint pinning belongs to the caller's deployment workflow.

    Fail-closed contract: the reranker must return exactly one finite score per
    submitted pair, a pair over the token budget is REJECTED (never truncated),
    and the output is always a subset of the candidates handed in — a reranker
    cannot add, rename or re-authorize a passage.
    """

    def __init__(
        self,
        source: CanonicalHybridCandidates,
        reranker: Any,
        tokenizer: Any,
        *,
        max_length: int = 512,
        batch_size: int = 1,
        top_k: int = 8,
        candidate_limit: int = 20,
    ) -> None:
        if type(source) is not CanonicalHybridCandidates:
            raise ValueError("canonical candidate source is required")
        if not callable(getattr(reranker, "compute_score", None)) or not callable(tokenizer):
            raise ValueError("reranker and tokenizer are required")
        for name, value, upper in (
            ("max_length", max_length, 512),
            ("batch_size", batch_size, 64),
            ("top_k", top_k, 80),
            ("candidate_limit", candidate_limit, 80),
        ):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError(f"{name} must be an int between 1 and {upper}")
        if top_k > candidate_limit:
            raise ValueError("top_k must not exceed candidate_limit")
        self._source = source
        self._reranker = reranker
        self._tokenizer = tokenizer
        self._max_length = max_length
        self._batch_size = batch_size
        self._top_k = top_k
        self._candidate_limit = candidate_limit

    def candidates(
        self, query: str, *, context: AuthorizationContext,
    ) -> list[RerankedCandidate]:
        observed = self._source.candidates(
            query, context=context, limit=self._candidate_limit,
        )
        if not observed:
            return []
        pairs = []
        for candidate in observed:
            # Reject over-budget pairs instead of truncating: a silently
            # truncated passage would be scored on text the citation claims.
            assert_pair_fits(
                self._tokenizer, query, candidate.chunk.text,
                max_length=self._max_length,
            )
            pairs.append([query, candidate.chunk.text])
        submitted = tuple(tuple(pair) for pair in pairs)
        raw = self._reranker.compute_score(
            pairs, batch_size=self._batch_size, max_length=self._max_length,
            normalize=True,
        )
        # Materialize only the expected number plus one: an infinite stream of
        # scores must not hang a request. Real accepts NumPy scalar scores, but
        # bool and numeric strings remain invalid scoring contracts.
        try:
            values = [raw] if isinstance(raw, Real) and not isinstance(raw, bool) else list(
                islice(raw, len(submitted) + 1)
            )
        except TypeError as exc:
            raise ValueError("reranker must return exactly one finite score per pair") from exc
        if tuple(tuple(pair) for pair in pairs) != submitted:
            raise ValueError("reranker modified scoring pairs")
        if (
            len(values) != len(submitted)
            or any(not isinstance(value, Real) or isinstance(value, bool) for value in values)
        ):
            raise ValueError("reranker must return exactly one finite score per pair")
        try:
            scores = [float(value) for value in values]
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("reranker must return exactly one finite score per pair") from exc
        # Check the values actually published, not just the objects before
        # float conversion: a Real subclass may override __float__.
        if (
            any(not math.isfinite(score) for score in scores)
            or tuple(tuple(pair) for pair in pairs) != submitted
        ):
            raise ValueError("reranker must return exactly one finite score per pair")
        order = sorted(
            range(len(observed)),
            key=lambda index: (-scores[index], observed[index].chunk.chunk_id),
        )
        return [
            RerankedCandidate(
                observed[index].chunk, scores[index], observed[index].rrf_score,
            )
            for index in order[: self._top_k]
        ]
