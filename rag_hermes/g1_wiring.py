"""Assembler une tranche G1 auditée avant la première requête utilisateur.

Cette construction ne fige pas Qdrant : elle est réservée aux essais contrôlés.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .acl import AuthorizationContext, Chunk
from .canonical_snapshot import PinnedDocumentSnapshot
from .index_integrity import IndexSnapshotReport, audit_qdrant_index
from .ingestion import Document
from .qdrant_repository import QdrantChunkRepository
from .retrieval import CanonicalAclSearch
from .service import AnswerResponse, AnswerTrace, RagService


@dataclass(frozen=True)
class AuditedReadOnlyService:
    """Surface de lecture seule : ne pas exposer import_document après audit."""

    _service: RagService

    def answer(self, question: str, *, context: AuthorizationContext) -> AnswerResponse:
        return self._service.answer(question, context=context)

    def answer_with_trace(self, question: str, *, context: AuthorizationContext) -> AnswerTrace:
        return self._service.answer_with_trace(question, context=context)


Generator = Callable[[str, tuple[Chunk, ...]], str]
Embedder = Callable[[str], list[float]]
Chunker = Callable[[Document], list[Chunk]]


def build_audited_g1_service(
    *,
    snapshot: PinnedDocumentSnapshot,
    expected_manifest_sha256: str,
    audit_client: Any,
    query_client: Any,
    collection: str,
    chunker: Chunker,
    embed: Embedder,
    generator: Generator | None = None,
    minimum_score: float = 0.2,
    top_k: int = 1,
) -> tuple[AuditedReadOnlyService, IndexSnapshotReport]:
    """Auditer toute la collection avant de fournir un chemin de réponse.

    La source et le digest épinglé sont exigés avant l'audit ; l'appelant doit
    figer les écritures et garantir l'indépendance des empreintes hors de Python.
    """
    if audit_client is query_client:
        raise ValueError("audit and query clients must be separate")
    if not snapshot.documents:
        raise ValueError("canonical source must not be empty")
    chunks = [chunk for doc in snapshot.documents.values() for chunk in chunker(doc)]
    if not chunks:
        raise ValueError("canonical source produced no chunks")
    report = audit_qdrant_index(
        audit_client, collection, chunks,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    ranked = QdrantChunkRepository(query_client, collection=collection, embed=embed)
    bridge = CanonicalAclSearch(
        ranked, snapshot.authority(), minimum_score=minimum_score,
        source=snapshot.source,
    )
    return AuditedReadOnlyService(RagService(
        repository=bridge, generator=generator,
        minimum_score=minimum_score, top_k=top_k,
    )), report
