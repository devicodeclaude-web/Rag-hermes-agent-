"""Explicit routing for the single-instance Qdrant V1 repository.

This is not a Python security boundary: the same process holds both clients.
Qdrant must enforce distinct collection-scoped credentials server-side.
"""
from __future__ import annotations

from typing import Any


class QdrantRepositoryClients:
    """Keep user queries off the write credential; never expose admin actions."""

    def __init__(self, read: Any, write: Any) -> None:
        if read is write:
            raise ValueError("query and write clients must be distinct")
        self._read = read
        self._write = write

    def query(self, collection: str, vector: list[float], *, query_filter: dict, limit: int = 10):
        return self._read.query(collection, vector, query_filter=query_filter, limit=limit)

    def query_sparse(self, collection: str, lexical_weights: object, *, context: Any, limit: int = 10):
        return self._read.query_sparse(collection, lexical_weights, context=context, limit=limit)

    def get_collection(self, collection: str):
        # Metadata is a pure read: keep it on the read identity, like the
        # startup preflight, so the write token is used only for the
        # replacement transaction below.
        return self._read.get_collection(collection)

    def scroll_filtered_page(self, collection: str, *, query_filter: dict, limit: int = 1, offset: int | str | None = None):
        # Deliberately on the write identity: this scan is the ownership check
        # of a replacement, not a user query.
        return self._write.scroll_filtered_page(
            collection, query_filter=query_filter, limit=limit, offset=offset,
        )

    def upsert(self, collection: str, points: list[dict], *, update_filter: dict | None = None):
        return self._write.upsert(collection, points, update_filter=update_filter)

    def retrieve_points(self, collection: str, ids: list[str | int]):
        return self._write.retrieve_points(collection, ids)

    def delete_points(self, collection: str, query_filter: dict):
        return self._write.delete_points(collection, query_filter)
