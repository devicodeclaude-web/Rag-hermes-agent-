"""Read-only diagnostic of an anchored canonical copy against a Qdrant index.

This is not repair or permission to resume service: the operator must stop all
writers and independently approve the anchor digest, tokenizer and collection.
Neither the local lock nor a Qdrant scroll provides a distributed snapshot.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
import re
from typing import Any, Callable

from .acl import Chunk
from .canonical_registry import (
    CanonicalDocumentRegistry, CanonicalStoreError, _ANCHOR_FILENAME,
    _STORE_FILENAME, _TRANSACTION_LOCK_FILENAME, _close_tracked_private_file,
    _open_private_dir, _open_private_file, _open_tracked_private_file,
    _read_recovery_file,
)
from .index_integrity import IndexSnapshotReport, audit_qdrant_index
from .ingestion import Document


def audit_canonical_copy_index(
    copy_dir: str | Path, *, anchor_sha256: str, client: Any,
    collection: str, chunker: Callable[[Document], list[Chunk]],
    page_size: int = 100,
) -> IndexSnapshotReport:
    """Compare all current documents' chunks to unfiltered Qdrant pages.

    A matching report proves only that the observed point IDs and payloads
    matched the supplied copy at scan time; vectors, hidden writes and later
    requests are not attested. `client` must be a separately credentialed,
    read-only operator client; `chunker` must be the service's approved profile.
    """
    if type(anchor_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", anchor_sha256) is None:
        raise ValueError("independently approved anchor digest required")
    path = Path(copy_dir)
    if not path.is_absolute():
        raise ValueError("absolute canonical copy path required")
    if not collection or type(page_size) is not int or not 1 <= page_size <= 1000:
        raise ValueError("collection and bounded page_size are required")
    if not callable(chunker):
        raise ValueError("chunker must be callable")

    directory = _open_private_dir(path)
    try:
        # Never let the ordinary registry read_guard create a missing lock.
        # Acquire the SAME inode for the whole replay and scroll, without write.
        lock_fd, lock_token = _open_tracked_private_file(
            directory, write=False, create=False, name=_TRANSACTION_LOCK_FILENAME,
        )
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            file_fd = _open_private_file(directory, write=False, create=False, name=_STORE_FILENAME)
            os.close(file_fd)
            anchor = CanonicalDocumentRegistry._read_anchor_file(directory)
            if anchor is None or anchor[0] == 0:
                raise CanonicalStoreError("nonempty canonical anchor required")
            original_anchor = _read_recovery_file(directory, _ANCHOR_FILENAME)
            if hashlib.sha256(original_anchor).hexdigest() != anchor_sha256:
                raise ValueError("canonical anchor digest differs from approved pin")
            # The registry verifies full replay against the anchor before any
            # Qdrant call. No files or locks are created on this path.
            registry = CanonicalDocumentRegistry(path)
            documents = registry.documents()
            if not documents:
                raise ValueError("canonical copy contains no documents")
            chunks: list[Chunk] = []
            for document in documents.values():
                passage_list = list(chunker(document))
                if not passage_list:
                    raise ValueError("canonical document produced no chunks")
                chunks.extend(passage_list)
            # `expected_manifest_sha256` is deliberately NOT passed: here the
            # independently approved value is the ANCHOR digest above, and the
            # manifest is derived from the anchored documents by the approved
            # chunker. Pinning a manifest digest as well would only restate
            # that derivation, not add an independent source.
            report = audit_qdrant_index(
                client, collection, chunks, page_size=page_size,
            )
            if (_read_recovery_file(directory, _ANCHOR_FILENAME) != original_anchor
                    or registry.documents() != documents):
                raise CanonicalStoreError("canonical copy changed during index audit")
            opened = os.fstat(directory)
            visible = os.stat(path, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino):
                raise CanonicalStoreError("canonical copy path changed during index audit")
            return report
        finally:
            _close_tracked_private_file(lock_token)
    finally:
        os.close(directory)
