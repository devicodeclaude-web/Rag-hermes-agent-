from __future__ import annotations

from typing import Callable, Mapping

from .qdrant_preflight import verify_collection_ready
from .qdrant_repository import QdrantChunkRepository
from .qdrant_rest import QdrantRestClient
from .service import RagService

Embedder = Callable[[str], list[float]]

_DEFAULT_COLLECTION = "hermes_chunks_v1"


def build_service(
    *,
    env: Mapping[str, str],
    embed: Embedder | None = None,
) -> RagService:
    """Build a RagService.

    - Without RAG_QDRANT_URL: in-memory lexical backend (development default).
    - With RAG_QDRANT_URL: a Qdrant-backed service. An `embed` callable is then
      mandatory — this module never chooses an embedding model implicitly.
    """
    qdrant_url = env.get("RAG_QDRANT_URL", "").strip()
    if not qdrant_url:
        return RagService()

    if embed is None:
        embed_lock = env.get("RAG_EMBED_LOCK", "").strip()
        if embed_lock:
            # Explicit operator opt-in to the pinned BGE-M3 checkpoint. The
            # model is loaded lazily on first use, so build stays offline-safe.
            from .embedding import LockedBgeM3Embedder

            embed = LockedBgeM3Embedder(lock_path=embed_lock)
        else:
            raise ValueError(
                "RAG_QDRANT_URL is set but no embedding function was provided; "
                "refusing to start a Qdrant-backed service without embeddings "
                "(pass embed=..., or set RAG_EMBED_LOCK to a pinned model lock)"
            )

    collection = env.get("RAG_QDRANT_COLLECTION", _DEFAULT_COLLECTION).strip()
    if not collection:
        raise ValueError("RAG_QDRANT_COLLECTION must not be empty")

    client = QdrantRestClient(qdrant_url)
    verify_collection_ready(client, collection)
    repository = QdrantChunkRepository(client, collection=collection, embed=embed)
    return RagService(repository=repository)
