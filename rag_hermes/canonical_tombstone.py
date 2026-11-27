"""Internal canonical-first document mask, issue #71 (not an endpoint).

Only the one-host, cooperative V1 writer path is in scope. This object is NOT
wired to the service: caller authentication, historical chunk-profile pinning,
collection alias resolution, G1 readers and reconciliation remain activation
requirements. A direct Qdrant client or another host bypasses these leases.
"""
from __future__ import annotations

from typing import Callable, Iterable

from .acl import Chunk
from .canonical_registry import CanonicalDocumentRegistry, CanonicalStoreError
from .ingestion import Document
from .qdrant_repository import QdrantChunkRepository


class CanonicalMaskIndexError(RuntimeError):
    """Canonical inactive was confirmed, but index sync needs reconciliation."""


class CanonicalTombstoneCoordinator:
    """One cooperative masked-write transaction, without public service wiring."""

    def __init__(
        self, registry: CanonicalDocumentRegistry, repository: QdrantChunkRepository, *,
        chunker: Callable[[Document], Iterable[Chunk]],
    ) -> None:
        if type(registry) is not CanonicalDocumentRegistry:
            raise ValueError("an exact canonical registry is required")
        if type(repository) is not QdrantChunkRepository:
            raise ValueError("an exact Qdrant chunk repository is required")
        if not callable(chunker):
            raise ValueError("a trusted chunker profile is required")
        self._registry = registry
        self._repository = repository
        self._chunker = chunker

    def mask_document(
        self, *, tenant_id: str, document_id: str, owner_id: str,
    ) -> int:
        """Publish inactive, then scan/mark/re-read Qdrant under both leases.

        The IDs supplied here are assertions to check against the live registry,
        NOT proof that the requester is authenticated. No endpoint calls this.
        A failure before the canonical append may leave the store unavailable
        (anchor ahead) or its durability unconfirmed; no Qdrant mark is tried.
        After an inactive publication, any index failure is non-idempotent and
        needs reconciliation, never implicit rollback or a blind retry.
        """
        if any(type(value) is not str or not value for value in (
            tenant_id, document_id, owner_id,
        )):
            raise ValueError("nonempty canonical tenant, document and owner are required")
        # Same order as CanonicalWriteThrough: response guard FIRST, document
        # lease SECOND. The first read chooses the lease key, not a write target.
        with self._registry.write_guard():
            current = self._registry.documents().get(document_id)
            if current is None:
                raise ValueError("unknown canonical document")
            if current.tenant_id != tenant_id or current.owner_id != owner_id:
                raise PermissionError("canonical document identity mismatch")
            if current.state != "active":
                raise ValueError("canonical document is already inactive")
            with self._repository._document_write_lease(tenant_id, document_id):
                # Revalidate LIVE state under both leases. The registry can
                # reject a changed/invalid anchor rather than trust a cache.
                fresh = self._registry.documents().get(document_id)
                if fresh != current or fresh is None or fresh.state != "active":
                    raise CanonicalStoreError("canonical document changed before mask")
                # Catch an already divergent index BEFORE masking canonically.
                # A second scan after publication remains mandatory: the
                # diagnostic alone is never write authorization.
                self._repository._preflight_document_tombstone_locked(
                    fresh, chunker=self._chunker,
                )
                self._registry.mark_inactive(document_id, owner_id=owner_id)
                # mark_inactive returned after durable publication. Re-read the
                # state and the historical manifest while holding both leases:
                # the LAST active record, not the new acl_version, has the
                # indexed point payloads.
                masked = self._registry.documents().get(document_id)
                manifest, inactive_ids = self._registry.last_active_manifest()
                if (
                    masked is None or masked.state != "inactive"
                    or masked.tenant_id != tenant_id or masked.owner_id != owner_id
                    or masked.doc_version != fresh.doc_version
                    or masked.acl_version != fresh.acl_version + 1
                    or manifest.get(document_id) != fresh
                    or document_id not in inactive_ids
                ):
                    raise CanonicalStoreError("canonical mask confirmation failed")
                try:
                    # The private core MUST NOT reacquire this same flock inode.
                    return self._repository._apply_document_tombstone_locked(
                        fresh, chunker=self._chunker,
                    )
                except Exception as exc:
                    raise CanonicalMaskIndexError(
                        "canonical document inactive; index reconciliation required"
                    ) from exc
