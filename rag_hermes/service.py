from __future__ import annotations

from dataclasses import dataclass

from .acl import AuthorizationContext, Chunk
from .ingestion import Document, chunk_document
from .retrieval import LexicalRetriever


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
    """Small in-memory application service for the local MVP."""

    def __init__(self, *, minimum_score: float = 0.2) -> None:
        if not 0.0 < minimum_score <= 1.0:
            raise ValueError("minimum_score must be between 0 and 1")
        self._minimum_score = minimum_score
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

    def answer(
        self,
        question: str,
        *,
        context: AuthorizationContext,
    ) -> AnswerResponse:
        results = LexicalRetriever(self._chunks).search(
            question,
            context=context,
            limit=1,
        )
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
