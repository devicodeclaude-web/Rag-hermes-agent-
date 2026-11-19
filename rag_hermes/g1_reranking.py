"""Locked reranking over canonical candidates: reorder only, never authorize.

The reranker score is NOT a calibrated confidence: it must not be turned into
an abstention threshold here. This stage only reorders and truncates candidates
that the canonical ACL/provenance barrier already accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from rag_hermes.acl import AuthorizationContext, Chunk
from rag_hermes.qdrant_repository import HybridCandidate
from rag_hermes.g1_hybrid_candidates import CanonicalHybridCandidates
from rag_hermes.reranker_budget import assert_pair_fits
from rag_hermes.reranker_scores import RerankerScoreError, ensure_finite_scores


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
    An optional `candidate_guard` runs on every accepted canonical candidate
    before tokenization/scoring; only the audited wrapper supplies a guard
    bound to its independently pinned manifest. A caller-supplied no-op guard
    offers no integrity guarantee.

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
        candidate_guard: Callable[[HybridCandidate], None] | None = None,
    ) -> None:
        if type(source) is not CanonicalHybridCandidates:
            raise ValueError("canonical candidate source is required")
        if not callable(getattr(reranker, "compute_score", None)) or not callable(tokenizer):
            raise ValueError("reranker and tokenizer are required")
        if candidate_guard is not None and not callable(candidate_guard):
            raise ValueError("candidate guard must be callable")
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
        self._candidate_guard = candidate_guard

    def candidates(
        self, query: str, *, context: AuthorizationContext,
    ) -> list[RerankedCandidate]:
        observed = self._source.candidates(
            query, context=context, limit=self._candidate_limit,
        )
        if not observed:
            return []
        if self._candidate_guard is not None:
            # The caller's optional manifest barrier runs before *any* passage
            # reaches the tokenizer or model. Not a sandbox for those callables.
            for candidate in observed:
                self._candidate_guard(candidate)
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
        # Garde PARTAGÉE avec le chemin service V1 (`rag_hermes.service`) et le
        # runner de campagne (`retrieval.score_authorized_pairs`) : scalaire
        # accepté, matérialisation bornée à n+1 (un flux de scores infini ne
        # doit pas faire boucler la requête), bool/chaînes refusés, scores
        # exigés FINIS.
        try:
            scores = ensure_finite_scores(raw, len(submitted))
        except RerankerScoreError as exc:
            raise ValueError("reranker must return exactly one finite score per pair") from exc
        # Vérifié APRÈS matérialisation et conversion : une sous-classe de Real
        # dont __float__ muterait les paires serait sinon scorée sur un texte
        # différent de celui que la citation revendique. Le message garde les
        # deux formulations (paires mutées / score par paire) : c'est le même
        # contrat rompu, et les deux sont épinglées par les tests.
        if tuple(tuple(pair) for pair in pairs) != submitted:
            raise ValueError(
                "reranker modified scoring pairs while converting: it must "
                "return exactly one finite score per pair"
            )
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
