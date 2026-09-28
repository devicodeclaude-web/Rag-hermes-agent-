from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .acl import AuthorizationContext, Chunk
from .ingestion import Document, chunk_document
from .retrieval import LexicalRetriever, SearchResult


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


class RagService:
    """Application service for the local MVP.

    Without a repository it keeps chunks in memory (lexical search). With a
    repository (e.g. QdrantChunkRepository) it persists chunks and delegates
    search, while keeping the same tenant/owner authorization guards.
    """

    def __init__(self, *, minimum_score: float = 0.2, repository: Any | None = None) -> None:
        if not 0.0 < minimum_score <= 1.0:
            raise ValueError("minimum_score must be between 0 and 1")
        self._minimum_score = minimum_score
        self._repository = repository
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
        if self._repository is not None:
            return self._repository.search(question, context=context, limit=1)
        return LexicalRetriever(self._chunks).search(
            question,
            context=context,
            limit=1,
        )

    def answer(
        self,
        question: str,
        *,
        context: AuthorizationContext,
    ) -> AnswerResponse:
        results = self._search(question, context=context)
        if not results or results[0].score < self._minimum_score:
            return AnswerResponse(
                answer="Je ne dispose pas de sources suffisantes pour répondre.",
                abstained=True,
                citations=(),
            )
        chunk = results[0].chunk
        citation = Citation(
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            source_uri=chunk.source_uri,
            quote=chunk.text,
        )
        return AnswerResponse(
            answer=chunk.text,
            abstained=False,
            citations=(citation,),
        )
