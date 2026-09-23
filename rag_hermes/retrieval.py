from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Any, Iterable

from .acl import AuthorizationContext, Chunk, filter_authorized
from .acl_authority import CanonicalAclAuthority
from .reranker_budget import assert_pair_fits

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class SearchResult:
    chunk: Chunk
    score: float


def _tokens(text: str) -> Counter[str]:
    return Counter(token.casefold() for token in _TOKEN_RE.findall(text))


class LexicalRetriever:
    """Dependency-free baseline; production retrieval will use Qdrant."""

    def __init__(self, chunks: Iterable[Chunk]):
        self._chunks = list(chunks)

    def search(self, query: str, *, context: AuthorizationContext | None, limit: int = 10) -> list[SearchResult]:
        if limit < 1:
            raise ValueError("limit must be positive")
        query_terms = _tokens(query)
        if not query_terms:
            return []
        authorized = filter_authorized(self._chunks, context)
        scored: list[SearchResult] = []
        for chunk in authorized:
            document_terms = _tokens(chunk.text)
            overlap = sum(min(count, document_terms.get(term, 0)) for term, count in query_terms.items())
            if overlap:
                scored.append(SearchResult(chunk=chunk, score=overlap / sum(query_terms.values())))
        scored.sort(key=lambda result: (-result.score, result.chunk.chunk_id))
        return scored[:limit]


@dataclass(frozen=True)
class AclBarrierCounters:
    examined: int = 0
    accepted: int = 0
    stale_acl_version: int = 0
    denied_by_authority: int = 0


@dataclass(frozen=True)
class RerankerBudgetCounters:
    checked_pairs: int
    maximum_pair_tokens: int
    rejected_pairs: int


def postfilter_candidates(candidates: Iterable[dict[str, Any]], context: AuthorizationContext, authority: CanonicalAclAuthority) -> tuple[list[dict[str, Any]], AclBarrierCounters]:
    accepted: list[dict[str, Any]] = []
    examined = stale = denied = 0
    for candidate in candidates:
        examined += 1
        payload = candidate.get("payload") or {}
        allowed, reason = authority.authorize(str(payload.get("document_id", "")), payload.get("acl_version"), context)
        if allowed:
            accepted.append(candidate)
        elif reason == "stale_acl_version":
            stale += 1
        else:
            denied += 1
    return accepted, AclBarrierCounters(examined, len(accepted), stale, denied)


def hybrid_rrf_indices(
    *,
    candidate_indices: list[int],
    dense_scores: list[float],
    sparse_scores: list[float],
    dense_limit: int,
    sparse_limit: int,
    output_limit: int,
    fusion_k: int = 60,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
) -> list[int]:
    if len(candidate_indices) != len(dense_scores) or len(candidate_indices) != len(sparse_scores):
        raise ValueError("candidate and score lengths differ")
    if min(dense_limit, sparse_limit, output_limit) < 1 or fusion_k < 1:
        raise ValueError("hybrid limits and fusion_k must be positive")
    dense_order = sorted(range(len(candidate_indices)), key=lambda item: (-dense_scores[item], candidate_indices[item]))[:dense_limit]
    sparse_order = sorted(range(len(candidate_indices)), key=lambda item: (-sparse_scores[item], candidate_indices[item]))[:sparse_limit]
    fused: dict[int, float] = {}
    for weight, order in ((dense_weight, dense_order), (sparse_weight, sparse_order)):
        for rank, position in enumerate(order, 1):
            index = candidate_indices[position]
            fused[index] = fused.get(index, 0.0) + weight / (fusion_k + rank)
    return [index for index, _ in sorted(fused.items(), key=lambda item: (-item[1], item[0]))[:output_limit]]


def score_authorized_pairs(reranker: Any, tokenizer: Any, query: str, candidates: list[dict[str, Any]], *, max_length: int, batch_size: int) -> tuple[list[float], RerankerBudgetCounters]:
    pairs: list[list[str]] = []
    lengths: list[int] = []
    for candidate in candidates:
        passage = str((candidate.get("payload") or {}).get("text", ""))
        lengths.append(assert_pair_fits(tokenizer, query, passage, max_length=max_length))
        pairs.append([query, passage])
    if not pairs:
        return [], RerankerBudgetCounters(0, 0, 0)
    raw = reranker.compute_score(pairs, batch_size=batch_size, max_length=max_length, normalize=True)
    scores = [float(raw)] if isinstance(raw, (float, int)) else [float(item) for item in raw]
    return scores, RerankerBudgetCounters(len(pairs), max(lengths), 0)
