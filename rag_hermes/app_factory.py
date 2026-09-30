from __future__ import annotations

from typing import Callable, Mapping

from .generator import OpenAICompatibleGenerator
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
    generator_url = env.get("RAG_GENERATOR_BASE_URL", "").strip()
    generator_model = env.get("RAG_GENERATOR_MODEL", "").strip()
    if bool(generator_url) != bool(generator_model):
        raise ValueError(
            "generator configuration requires both RAG_GENERATOR_BASE_URL "
            "and RAG_GENERATOR_MODEL"
        )
    generator = (
        OpenAICompatibleGenerator(
            base_url=generator_url,
            model=generator_model,
            api_key=env.get("RAG_GENERATOR_API_KEY", ""),
        )
        if generator_url
        else None
    )

    top_k_raw = env.get("RAG_TOP_K", "").strip()
    if top_k_raw:
        try:
            top_k = int(top_k_raw)
        except ValueError as exc:
            raise ValueError("RAG_TOP_K must be a positive integer") from exc
        if top_k < 1:
            raise ValueError("RAG_TOP_K must be a positive integer")
    else:
        top_k = 1

    retrieval_k_raw = env.get("RAG_RETRIEVAL_K", "").strip()
    if retrieval_k_raw:
        try:
            retrieval_k = int(retrieval_k_raw)
        except ValueError as exc:
            raise ValueError("RAG_RETRIEVAL_K must be a positive integer") from exc
        if retrieval_k < 1:
            raise ValueError("RAG_RETRIEVAL_K must be a positive integer")
    else:
        retrieval_k = top_k

    qdrant_url = env.get("RAG_QDRANT_URL", "").strip()
    if not qdrant_url:
        return RagService(
            generator=generator, top_k=top_k, retrieval_k=retrieval_k
        )

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
    return RagService(
        repository=repository,
        generator=generator,
        top_k=top_k,
        retrieval_k=retrieval_k,
    )
