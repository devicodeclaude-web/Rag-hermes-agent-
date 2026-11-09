from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import math
import re
from typing import Any, Callable, Iterable

from .acl import AuthorizationContext, Chunk, filter_authorized
from .acl_authority import CanonicalAclAuthority
from .ingestion import Document
from .qdrant_filter import build_qdrant_filter
from .reranker_budget import assert_pair_fits

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class SearchResult:
    chunk: Chunk
    score: float
    threshold_score: float | None = None

    @property
    def effective_threshold_score(self) -> float:
        return self.score if self.threshold_score is None else self.threshold_score


class CanonicalAclError(PermissionError):
    """Refus émis par la barrière canonique, distinct d'une panne de stockage."""


class CanonicalAclSearch:
    """Recheck ranked repository candidates against the canonical ACL before answering."""

    def __init__(
        self, ranked_search: Any, authority: CanonicalAclAuthority, *,
        minimum_score: float = 0.2,
        source: Callable[[str], Document | None] | None = None,
    ) -> None:
        if not 0.0 < minimum_score <= 1.0:
            raise ValueError("minimum_score must be between 0 and 1")
        self._ranked_search = ranked_search
        self._authority = authority
        self._source = source
        self.minimum_score = minimum_score

    def replace_document(self, document: Any, chunks: Iterable[Chunk]) -> Any:
        return self._ranked_search.replace_document(document, chunks)

    def search(
        self, query: str, *, context: AuthorizationContext, limit: int = 10
    ) -> list[SearchResult]:
        if not isinstance(context, AuthorizationContext):
            raise ValueError("authorization context is required")
        if limit < 1:
            raise ValueError("limit must be positive")
        if limit > 128:
            raise ValueError("limit exceeds canonical scan budget")
        requested = limit
        while True:
            results = self._ranked_search.search(query, context=context, limit=requested)
            if len(results) > requested:
                raise ValueError("ranked search exceeded requested limit")
            accepted, stale_authorized = self._recheck(results, context)
            eligible = [
                result for result in accepted
                if result.effective_threshold_score >= self.minimum_score
            ]
            if len(eligible) >= limit or len(results) < requested:
                break
            if requested == 128:
                raise CanonicalAclError("canonical candidate scan budget exhausted")
            requested = min(128, requested * 2)
        if stale_authorized and not eligible:
            raise CanonicalAclError("stale ACL index has no usable authorized candidates")
        return eligible[:limit]

    def _recheck(
        self, results: list[SearchResult], context: AuthorizationContext
    ) -> tuple[list[SearchResult], bool]:
        accepted: list[SearchResult] = []
        stale_authorized = False
        for result in results:
            chunk = result.chunk
            policy = self._authority.policy_for(chunk.document_id)
            allowed, reason = self._authority.authorize(
                chunk.document_id, chunk.acl_version, context
            )
            if allowed:
                if policy is None:
                    raise CanonicalAclError("canonical policy missing after authorization")
                if (
                    chunk.tenant_id != policy.tenant_id
                    or chunk.visibility != policy.visibility
                    or chunk.owner_id != policy.owner_id
                    or chunk.classification != policy.classification
                    or set(chunk.allowed_groups) != set(policy.allowed_groups)
                    or set(chunk.allowed_users) != set(policy.allowed_users)
                ):
                    raise CanonicalAclError("ACL payload conflicts with canonical policy")
                source = self._source
                if source is None:
                    raise CanonicalAclError("trusted provenance source is required")
                document = source(chunk.document_id)
                if document is None:
                    raise CanonicalAclError("canonical provenance document missing")
                digest = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
                if (
                    document.document_id != chunk.document_id
                    or document.tenant_id != policy.tenant_id
                    or document.visibility != policy.visibility
                    or document.owner_id != policy.owner_id
                    or document.classification != policy.classification
                    or set(document.allowed_groups) != set(policy.allowed_groups)
                    or set(document.allowed_users) != set(policy.allowed_users)
                    or document.acl_version != policy.acl_version
                    or document.doc_version != chunk.doc_version
                    or document.source_uri != chunk.source_uri
                    or digest != chunk.source_sha
                    or (chunk.content_hash and chunk.content_hash != digest)
                    or not (0 <= chunk.start_offset < chunk.end_offset <= len(document.content))
                    or document.content[chunk.start_offset:chunk.end_offset] != chunk.text
                ):
                    raise CanonicalAclError("candidate provenance conflicts with canonical document")
                if filter_authorized([chunk], context):
                    accepted.append(result)
            elif reason == "stale_acl_version" and policy is not None and policy.allows(context):
                stale_authorized = True
        return accepted, stale_authorized


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
        document_terms = [_tokens(chunk.text) for chunk in authorized]
        if not document_terms:
            return []
        document_frequency: Counter[str] = Counter()
        for terms in document_terms:
            document_frequency.update(terms.keys())
        document_count = len(document_terms)
        average_length = sum(sum(terms.values()) for terms in document_terms) / document_count
        k1 = 1.2
        b = 0.75
        scored: list[tuple[float, SearchResult]] = []
        query_length = sum(query_terms.values())
        for chunk, terms in zip(authorized, document_terms):
            document_length = sum(terms.values())
            raw_score = 0.0
            overlap = 0
            for term, query_count in query_terms.items():
                term_frequency = terms.get(term, 0)
                if not term_frequency:
                    continue
                overlap += min(query_count, term_frequency)
                inverse_document_frequency = math.log(
                    1.0
                    + (document_count - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                )
                saturation = (
                    term_frequency * (k1 + 1.0)
                    / (
                        term_frequency
                        + k1 * (1.0 - b + b * document_length / average_length)
                    )
                )
                raw_score += inverse_document_frequency * saturation * query_count
            if raw_score:
                # BM25 determines rank and the public score order. Keep the
                # established overlap ratio separately for minimum_score.
                score = raw_score / (raw_score + 1.0)
                threshold_score = overlap / query_length
                scored.append(
                    (
                        raw_score,
                        SearchResult(
                            chunk=chunk,
                            score=score,
                            threshold_score=threshold_score,
                        ),
                    )
                )
        scored.sort(key=lambda item: (-item[0], item[1].chunk.chunk_id))
        return [result for _rank_score, result in scored[:limit]]


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


def retrieve_authorized_candidates(
    client: Any,
    collection: str,
    vector: list[float],
    *,
    context: AuthorizationContext,
    authority: CanonicalAclAuthority,
    limit: int,
) -> tuple[list[dict[str, Any]], AclBarrierCounters]:
    """Production path: Qdrant prefilter then canonical ACL recheck."""
    candidates = client.query(
        collection,
        vector,
        query_filter=build_qdrant_filter(context),
        limit=limit,
    )
    return postfilter_candidates(candidates, context, authority)


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
    if len(scores) != len(pairs) or any(not math.isfinite(score) for score in scores):
        raise ValueError("reranker must return exactly one finite score per pair")
    return scores, RerankerBudgetCounters(len(pairs), max(lengths), 0)
