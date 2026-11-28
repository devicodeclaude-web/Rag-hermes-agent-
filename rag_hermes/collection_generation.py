"""Read-only observation of an operator-provisioned Qdrant generation.

An observation is NOT an original-ingestion receipt, a server-immutable UUID,
or authorization to mutate. It must later match contemporaneous canonical and
external operator evidence under the documented lifecycle exclusion.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class CollectionGenerationObservation:
    endpoint: str
    collection: str
    generation: str


def observe_collection_generation(client: Any, collection: str) -> CollectionGenerationObservation:
    """Refuse aliases and missing/ill-typed metadata before any indexed write."""
    if type(collection) is not str or not collection:
        raise ValueError("physical collection name required")
    endpoint = getattr(client, "base_url", None)
    if type(endpoint) is not str or not endpoint:
        raise ValueError("Qdrant endpoint is not attested")
    names = client.list_collections()
    if type(names) is not tuple or collection not in names:
        raise ValueError("physical collection is not in Qdrant's collection list")
    info = client.get_collection(collection)
    config = info.get("config") if type(info) is dict else None
    metadata = config.get("metadata") if type(config) is dict else None
    generation = metadata.get("hermes_generation_uuid") if type(metadata) is dict else None
    try:
        valid = (type(generation) is str and str(UUID(generation)) == generation
                 and UUID(generation).version == 4)
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("original collection generation metadata is missing or invalid")
    return CollectionGenerationObservation(endpoint, collection, generation)


def require_matching_generation(
    client: Any, original: CollectionGenerationObservation,
) -> CollectionGenerationObservation:
    """Compare with an externally and historically approved original record.

    This function does not approve that record, its timestamp or lifecycle
    exclusion; callers must obtain that evidence independently of Qdrant.
    """
    if type(original) is not CollectionGenerationObservation:
        raise ValueError("original collection generation receipt is required")
    if getattr(client, "base_url", None) != original.endpoint:
        raise ValueError("collection generation mismatch")
    observed = observe_collection_generation(client, original.collection)
    if observed != original:
        raise ValueError("collection generation mismatch")
    return observed
