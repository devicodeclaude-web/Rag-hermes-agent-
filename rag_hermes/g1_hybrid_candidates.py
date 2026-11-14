"""Candidate-only canonical barrier for hybrid retrieval; no answer or abstention."""
from __future__ import annotations

from pathlib import Path

from rag_hermes.acl import AuthorizationContext
from rag_hermes.canonical_snapshot import load_pinned_document_snapshot
from rag_hermes.qdrant_repository import HybridCandidate, QdrantChunkRepository
from rag_hermes.retrieval import CanonicalAclError, CanonicalAclSearch, SearchResult


class CanonicalHybridCandidates:
    """Recheck observed RRF hits against a pinned source independent of Qdrant.

    A returned empty list means *no usable hit in this bounded window*, not an
    honest no-answer verdict. This class cannot certify omitted Qdrant hits.
    """

    def __init__(
        self, repository: QdrantChunkRepository, source_path: Path, *, expected_sha256: str,
    ):
        if type(repository) is not QdrantChunkRepository or not isinstance(source_path, Path):
            raise ValueError("hybrid repository and canonical source path are required")
        snapshot = load_pinned_document_snapshot(source_path, expected_sha256=expected_sha256)
        self._repository = repository
        self._snapshot = snapshot
        self._authority = snapshot.authority()
        self._barrier = CanonicalAclSearch(
            repository, self._authority, source=snapshot.source,
        )

    def candidates(
        self, query: str, *, context: AuthorizationContext, limit: int = 20,
    ) -> list[HybridCandidate]:
        if type(limit) is not int or not 1 <= limit <= 80:
            raise ValueError("hybrid candidate limit must be between 1 and 80")
        observed = self._repository.hybrid_candidates(
            query, context=context, output_limit=80, include_denied=True,
        )
        ranked: list[HybridCandidate] = []
        for item in observed:
            chunk = item.chunk
            document = self._snapshot.source(chunk.document_id)
            if not item.authorized_by_index:
                # The payload ACL hid this hit. Only the canonical authority can
                # say whether that was a legitimately foreign document or an
                # index that is MORE restrictive than the canonical source: the
                # latter would otherwise leave an empty window indistinguishable
                # from an honest no-answer. An unknown document stays a foreign
                # hit, since the snapshot carries no claim about it.
                policy = self._authority.policy_for(chunk.document_id)
                if policy is not None and policy.allows(context):
                    raise CanonicalAclError(
                        "observed ACL conflicts with canonical document"
                    )
                continue
            if document is None:
                raise CanonicalAclError("missing canonical document for observed candidate")
            # An index hit whose indexed ACL grants this request but whose
            # canonical owner/visibility changed must not become an empty
            # window just because authorize() denies the caller first.
            if (
                chunk.tenant_id != document.tenant_id
                or chunk.visibility != document.visibility
                or chunk.owner_id != document.owner_id
                or chunk.classification != document.classification
                or set(chunk.allowed_groups) != set(document.allowed_groups)
                or set(chunk.allowed_users) != set(document.allowed_users)
            ):
                raise CanonicalAclError("observed ACL conflicts with canonical document")
            ranked.append(item)
        accepted, stale_authorized = self._barrier._recheck(
            [SearchResult(item.chunk, item.rrf_score) for item in ranked], context
        )
        if stale_authorized and not accepted:
            raise CanonicalAclError("stale ACL index has no usable authorized candidates")
        return [
            HybridCandidate(item.chunk, item.score, authorized_by_index=True)
            for item in accepted[:limit]
        ]
