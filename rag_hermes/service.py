from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .acl import AuthorizationContext, Chunk
from .answering import (
    ABSTENTION_ANSWER, AnswerResponse, AnswerTrace, Citation, answer_from_evidence,
)
from .generator import GenerationError
from .ingestion import Document, chunk_document
from .reranker_scores import RerankerScoreError, ensure_finite_scores
from .retrieval import CanonicalAclSearch, LexicalRetriever, SearchResult

# Citation, AnswerResponse, AnswerTrace et answer_from_evidence vivent dans
# `rag_hermes.answering` : la voie G1 doit pouvoir rendre une reponse citee sans
# importer ce service (donc sans cycle quand le cablage inverse arrivera).
# Ils restent reexportes ici pour les appelants historiques.


@dataclass(frozen=True)
class ImportResult:
    document_id: str
    chunk_count: int


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
        chunker: Callable[[Document], list[Chunk]] = chunk_document,
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
        if isinstance(repository, CanonicalAclSearch) and repository.minimum_score != minimum_score:
            raise ValueError("repository and service minimum_score must match")
        if not callable(chunker):
            raise ValueError("chunker must be callable")
        self._minimum_score = minimum_score
        self._repository = repository
        self._generator = generator
        self._reranker = reranker
        self._chunker = chunker
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
        chunks = self._chunker(document)
        if not chunks:
            raise ValueError("an import must carry at least one passage")
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
        if isinstance(self._repository, CanonicalAclSearch):
            # Hold the same local shared lease across retrieval, reranking and
            # generation. The write-through takes its exclusive counterpart
            # across canonical publication AND Qdrant replacement.
            with self._repository.read_guard():
                return self._answer_with_trace_in_guard(question, context=context)
        return self._answer_with_trace_in_guard(question, context=context)

    def _answer_with_trace_in_guard(
        self, question: str, *, context: AuthorizationContext
    ) -> AnswerTrace:
        results = self._search(question, context=context)
        if not results or not any(
            result.effective_threshold_score >= self._minimum_score
            for result in results
        ):
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
            if result.effective_threshold_score >= self._minimum_score
        )
        # Optional reranking: rescore the authorized candidates with the
        # injected cross-encoder, then keep the best top_k. The reranker never
        # widens authorization — it only reorders already-authorized chunks.
        if self._reranker is not None:
            scores = self._reranker(question, evidence)
            if not isinstance(scores, list):
                # An injected reranker returning malformed output is a server-side
                # generation-component failure, not a client request error, so it
                # must fail closed as GenerationError (mapped to 502) rather than a
                # bare ValueError that the HTTP layer would report as a 400.
                raise GenerationError(
                    "reranker must return one score per candidate chunk"
                )
            # Même garde que le chemin G1 (`g1_reranking`) : compte exact,
            # nombres réels, scores FINIS. Un NaN rendrait le tri non
            # transitif et ±inf épinglerait un candidat en tête.
            try:
                finite_scores = ensure_finite_scores(scores, len(evidence))
            except RerankerScoreError as exc:
                raise GenerationError(
                    "reranker must return one finite score per candidate chunk"
                ) from exc
            ordered = sorted(
                range(len(evidence)),
                key=lambda index: (-finite_scores[index], evidence[index].chunk_id),
            )
            evidence = tuple(evidence[index] for index in ordered[: self._top_k])
        else:
            evidence = evidence[: self._top_k]
        # strict_citations=False : le chemin V1 garde son comportement
        # historique (un marqueur hors fenetre est ignore, pas fatal), epingle
        # par test_service.test_pathological_marker_from_generator_is_ignored_
        # without_error. Le pilote G1 opte, lui, pour le mode strict.
        return answer_from_evidence(
            question, evidence, generator=self._generator, strict_citations=False,
        )
