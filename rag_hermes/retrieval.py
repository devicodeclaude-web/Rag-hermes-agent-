from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Iterable

from .acl import AuthorizationContext, Chunk, filter_authorized

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

    def search(
        self,
        query: str,
        *,
        context: AuthorizationContext | None,
        limit: int = 10,
    ) -> list[SearchResult]:
        if limit < 1:
            raise ValueError("limit must be positive")
        query_terms = _tokens(query)
        if not query_terms:
            return []

        authorized = filter_authorized(self._chunks, context)
        scored: list[SearchResult] = []
        for chunk in authorized:
            document_terms = _tokens(chunk.text)
            overlap = sum(
                min(count, document_terms.get(term, 0))
                for term, count in query_terms.items()
            )
            if overlap:
                score = overlap / sum(query_terms.values())
                scored.append(SearchResult(chunk=chunk, score=score))

        scored.sort(key=lambda result: (-result.score, result.chunk.chunk_id))
        return scored[:limit]
