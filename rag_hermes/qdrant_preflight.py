from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class QdrantPreflightError(RuntimeError):
    """The configured Qdrant backend cannot safely serve ACL-filtered traffic."""


class CollectionMetadataClient(Protocol):
    def get_collection(self, collection: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RequiredPayloadIndex:
    data_type: str
    is_tenant: bool = False


# Keep this contract aligned with qdrant/payload-indexes.json. Every field is
# used by document replacement, ACL filtering, tombstone filtering, or audit
# traceability, so startup fails closed if any index is absent or has drifted.
REQUIRED_PAYLOAD_INDEXES: dict[str, RequiredPayloadIndex] = {
    "tenant_id": RequiredPayloadIndex("keyword", is_tenant=True),
    "visibility": RequiredPayloadIndex("keyword"),
    "owner_id": RequiredPayloadIndex("keyword"),
    "allowed_group_ids": RequiredPayloadIndex("keyword"),
    "allowed_user_ids": RequiredPayloadIndex("keyword"),
    "classification": RequiredPayloadIndex("integer"),
    "tombstone": RequiredPayloadIndex("bool"),
    "document_id": RequiredPayloadIndex("keyword"),
    "doc_version": RequiredPayloadIndex("integer"),
    "acl_version": RequiredPayloadIndex("integer"),
    "source_sha": RequiredPayloadIndex("keyword"),
}


def _fail(collection: str, detail: str) -> QdrantPreflightError:
    return QdrantPreflightError(
        f"Qdrant collection {collection!r} is not ready: {detail}. "
        "Create the collection and all indexes from qdrant/payload-indexes.json "
        "before starting the service"
    )


def verify_collection_ready(
    client: CollectionMetadataClient,
    collection: str,
) -> dict[str, Any]:
    """Verify the Qdrant schema required by the ACL-safe repository.

    This function only reads collection metadata. It never creates or modifies
    infrastructure: operators must provision the collection explicitly.
    """
    collection = collection.strip()
    if not collection:
        raise ValueError("collection must not be empty")

    try:
        metadata = client.get_collection(collection)
    except RuntimeError as exc:
        detail = str(exc)
        if "404" in detail or "doesn't exist" in detail:
            raise _fail(collection, "collection does not exist") from exc
        raise _fail(collection, f"Qdrant unavailable or unreadable ({detail})") from exc

    if not isinstance(metadata, dict):
        raise _fail(collection, "malformed collection metadata")

    config = metadata.get("config")
    if not isinstance(config, dict):
        raise _fail(collection, "missing collection config")
    params = config.get("params")
    if not isinstance(params, dict):
        raise _fail(collection, "missing collection params")
    vectors = params.get("vectors")
    if not isinstance(vectors, dict):
        raise _fail(collection, "missing vector configuration")
    dense = vectors.get("dense")
    if not isinstance(dense, dict):
        raise _fail(collection, 'missing named vector "dense"')
    vector_size = dense.get("size")
    if not isinstance(vector_size, int) or isinstance(vector_size, bool) or vector_size < 1:
        raise _fail(collection, 'named vector "dense" has an invalid size')

    payload_schema = metadata.get("payload_schema")
    if not isinstance(payload_schema, dict):
        raise _fail(collection, "missing or malformed payload_schema")

    for field, expected in REQUIRED_PAYLOAD_INDEXES.items():
        entry = payload_schema.get(field)
        if not isinstance(entry, dict):
            raise _fail(collection, f"missing or malformed payload index {field!r}")
        actual_type = entry.get("data_type")
        if actual_type != expected.data_type:
            raise _fail(
                collection,
                f"payload index {field!r} must have type {expected.data_type!r}, "
                f"got {actual_type!r}",
            )
        if expected.is_tenant:
            index_params = entry.get("params")
            if not isinstance(index_params, dict) or index_params.get("is_tenant") is not True:
                raise _fail(
                    collection,
                    f"payload index {field!r} must declare is_tenant=true",
                )
        else:
            index_params = entry.get("params")
            if isinstance(index_params, dict) and index_params.get("is_tenant") is True:
                raise _fail(
                    collection,
                    f"payload index {field!r} must not declare is_tenant=true",
                )

    return {
        "collection": collection,
        "vector_name": "dense",
        "vector_size": vector_size,
        "tenant_index": True,
        "verified_indexes": list(REQUIRED_PAYLOAD_INDEXES),
    }
