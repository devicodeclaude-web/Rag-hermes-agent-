from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from .acl import AuthorizationContext, Chunk
from .generator import ABSTENTION_ANSWER, GenerationError
from .ingestion import Document, chunk_document
from .retrieval import LexicalRetriever, SearchResult

_CITATION_MARKER_RE = re.compile(r"\[S(\d+)\]")


@dataclass(frozen=True)
class ImportResult:
    document_id: str
    chunk_count: int


@dataclass(frozen=True)
class Citation:
    document_id: str
    chunk_id: str
    source_uri: str
    quote: str


@dataclass(frozen=True)
class AnswerResponse:
    answer: str
    abstained: bool
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class AnswerTrace:
    """Internal evaluation trace from the production answer path."""

    response: AnswerResponse
    retrieved_chunks: tuple[Chunk, ...]
    cited_chunks: tuple[Chunk, ...]


class RagService:
    """Application service for the local MVP.

    Without a repository it keeps chunks in memory (lexical search). With a
    repository (e.g. QdrantChunkRepository) it persists chunks and delegates
    search, while keeping the same tenant/owner authorization guards.
    """

    def __init__(
        self,
        *,
        minimum_score: float = 0.2,
        repository: Any | None = None,
        generator: Callable[[str, tuple[Chunk, ...]], str] | None = None,
        reranker: Callable[[str, tuple[Chunk, ...]], list[float]] | None = None,
        retrieval_k: int | None = None,
        top_k: int = 1,
    ) -> None:
        if not 0.0 < minimum_score <= 1.0:
            raise ValueError("minimum_score must be between 0 and 1")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        # retrieval_k is how many candidates are fetched before reranking; it
        # defaults to top_k (no widening) and can never be smaller than top_k.
        if retrieval_k is None:
            retrieval_k = top_k
        if retrieval_k < top_k:
            raise ValueError("retrieval_k must be >= top_k")
        self._minimum_score = minimum_score
        self._repository = repository
        self._generator = generator
        self._reranker = reranker
        self._retrieval_k = retrieval_k
        self._top_k = top_k
        self._chunks: list[Chunk] = []
        self._document_owners: dict[tuple[str, str], str] = {}

    def import_document(
        self,
        document: Document,
        *,
        context: AuthorizationContext,
    ) -> ImportResult:
        if document.tenant_id != context.tenant_id:
            raise PermissionError("document tenant must match authorization context")
        if document.owner_id != context.user_id:
            raise PermissionError("only the document owner can import it")
        document_key = (document.tenant_id, document.document_id)
        existing_owner = self._document_owners.get(document_key)
        if existing_owner is not None and existing_owner != context.user_id:
            raise PermissionError("only the existing document owner can replace it")
        chunks = chunk_document(document)
        if self._repository is not None:
            result = self._repository.replace_document(document, chunks)
            self._document_owners[document_key] = document.owner_id
            return ImportResult(result.document_id, result.chunk_count)
        self._chunks = [
            chunk
            for chunk in self._chunks
            if not (
                chunk.document_id == document.document_id
                and chunk.tenant_id == document.tenant_id
            )
        ]
        self._chunks.extend(chunks)
        self._document_owners[document_key] = document.owner_id
        return ImportResult(document.document_id, len(chunks))

    def _search(
        self, question: str, *, context: AuthorizationContext
    ) -> list[SearchResult]:
        fetch = self._retrieval_k if self._reranker is not None else self._top_k
        if self._repository is not None:
            return self._repository.search(question, context=context, limit=fetch)
        return LexicalRetriever(self._chunks).search(
            question,
            context=context,
            limit=fetch,
        )

    def answer(
        self,
        question: str,
        *,
        context: AuthorizationContext,
    ) -> AnswerResponse:
        return self.answer_with_trace(question, context=context).response

    def answer_with_trace(
        self,
        question: str,
        *,
        context: AuthorizationContext,
    ) -> AnswerTrace:
        """Answer through the normal path and expose evidence for evaluation."""
        results = self._search(question, context=context)
        if not results or results[0].score < self._minimum_score:
            response = AnswerResponse(
                answer=ABSTENTION_ANSWER,
                abstained=True,
                citations=(),
            )
            return AnswerTrace(response, (), ())
        # Only chunks at or above the minimum score become authorized evidence.
        evidence = tuple(
            result.chunk
            for result in results
            if result.score >= self._minimum_score
        )
        # Optional reranking: rescore the authorized candidates with the
        # injected cross-encoder, then keep the best top_k. The reranker never
        # widens authorization — it only reorders already-authorized chunks.
        if self._reranker is not None:
            scores = self._reranker(question, evidence)
            if not isinstance(scores, list) or len(scores) != len(evidence):
                # An injected reranker returning malformed output is a server-side
                # generation-component failure, not a client request error, so it
                # must fail closed as GenerationError (mapped to 502) rather than a
                # bare ValueError that the HTTP layer would report as a 400.
                raise GenerationError(
                    "reranker must return one score per candidate chunk"
                )
            ordered = sorted(
                range(len(evidence)),
                key=lambda index: (-float(scores[index]), evidence[index].chunk_id),
            )
            evidence = tuple(evidence[index] for index in ordered[: self._top_k])
        else:
            evidence = evidence[: self._top_k]
        if not self._generator:
            # Extractive default: single best chunk with its citation.
            top = evidence[0]
            response = AnswerResponse(
                answer=top.text,
                abstained=False,
                citations=(
                    Citation(
                        document_id=top.document_id,
                        chunk_id=top.chunk_id,
                        source_uri=top.source_uri,
                        quote=top.text,
                    ),
                ),
            )
            return AnswerTrace(response, evidence, (top,))
        answer = self._generator(question, evidence)
        if answer == ABSTENTION_ANSWER:
            response = AnswerResponse(answer=answer, abstained=True, citations=())
            return AnswerTrace(response, evidence, ())
        # Keep only citations the generator actually referenced via [Sn]. The
        # markers are compared as strings against the allowed set, so an
        # attacker-controlled marker with an astronomically long digit run can
        # never trigger an int() conversion here. Preserve first-cited order,
        # deduplicated.
        allowed = {str(position): position - 1 for position in range(1, len(evidence) + 1)}
        cited_indices: list[int] = []
        for marker in _CITATION_MARKER_RE.findall(answer):
            index = allowed.get(marker)
            if index is not None and index not in cited_indices:
                cited_indices.append(index)
        citations = tuple(
            Citation(
                document_id=evidence[index].document_id,
                chunk_id=evidence[index].chunk_id,
                source_uri=evidence[index].source_uri,
                quote=evidence[index].text,
            )
            for index in cited_indices
        )
        # Fail closed: a non-abstention answer must resolve to at least one
        # citation, regardless of which generator is injected. The bundled
        # generator already enforces this, but the service must not trust an
        # arbitrary generator to keep the marker->citation invariant.
        if not citations:
            raise GenerationError(
                "generated answer resolved to zero valid citations"
            )
        response = AnswerResponse(
            answer=answer,
            abstained=False,
            citations=citations,
        )
        cited_chunks = tuple(evidence[index] for index in cited_indices)
        return AnswerTrace(response, evidence, cited_chunks)
