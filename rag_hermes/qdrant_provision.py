from __future__ import annotations

from typing import Any, Protocol

from .qdrant_preflight import REQUIRED_PAYLOAD_INDEXES, verify_collection_ready


class QdrantProvisionError(RuntimeError):
    """Existing Qdrant infrastructure is incompatible with the requested spec."""


class ProvisioningClient(Protocol):
    def collection_exists(self, collection: str) -> bool: ...

    def create_collection(
        self, collection: str, *, vector_size: int, distance: str = "Cosine"
    ) -> dict[str, Any]: ...

    def create_payload_index(
        self,
        collection: str,
        field_name: str,
        field_schema: str | dict[str, Any],
    ) -> dict[str, Any]: ...

    def get_collection(self, collection: str) -> dict[str, Any]: ...


def _validated_indexes(specification: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(specification, dict):
        raise QdrantProvisionError("index specification must be an object")

    required_top_level = {
        "collection",
        "payload_indexes",
        "verified_against",
        "minimum_version_for_is_tenant",
    }
    if set(specification) != required_top_level:
        raise QdrantProvisionError(
            "index specification has missing or unknown top-level properties"
        )
    for field in (
        "collection",
        "verified_against",
        "minimum_version_for_is_tenant",
    ):
        value = specification[field]
        if type(value) is not str or not value.strip():
            raise QdrantProvisionError(
                f"index specification field {field!r} must be a non-empty string"
            )

    indexes = specification["payload_indexes"]
    if not isinstance(indexes, list):
        raise QdrantProvisionError("index specification must contain payload_indexes")

    declared: dict[str, tuple[str, bool, str]] = {}
    for item in indexes:
        if not isinstance(item, dict) or set(item) != {"field_name", "field_schema"}:
            raise QdrantProvisionError(
                "index specification contains a malformed entry or unknown property"
            )
        field_name = item["field_name"]
        if type(field_name) is not str or not field_name or field_name in declared:
            raise QdrantProvisionError(
                "index specification contains an empty, non-string, or duplicate field name"
            )
        field_schema = item["field_schema"]
        if type(field_schema) is str and field_schema:
            data_type, is_tenant, shape = field_schema, False, "string"
        elif isinstance(field_schema, dict):
            if set(field_schema) != {"type", "is_tenant"}:
                raise QdrantProvisionError(
                    f"index specification has invalid properties for {field_name!r}"
                )
            data_type = field_schema["type"]
            is_tenant = field_schema["is_tenant"]
            if type(data_type) is not str or not data_type or type(is_tenant) is not bool:
                raise QdrantProvisionError(
                    f"index specification has invalid schema types for {field_name!r}"
                )
            shape = "object"
        else:
            raise QdrantProvisionError(
                f"index specification has invalid schema for {field_name!r}"
            )
        declared[field_name] = (data_type, is_tenant, shape)

    required = {
        name: (
            definition.data_type,
            definition.is_tenant,
            "object" if definition.is_tenant else "string",
        )
        for name, definition in REQUIRED_PAYLOAD_INDEXES.items()
    }
    if declared != required:
        raise QdrantProvisionError(
            "index specification does not exactly match the required ACL contract"
        )
    return indexes


def provision_collection(
    client: ProvisioningClient,
    *,
    collection: str,
    vector_size: int,
    specification: dict[str, Any],
) -> dict[str, Any]:
    """Create an absent Qdrant collection and its declared payload indexes."""
    collection = collection.strip()
    if not collection:
        raise ValueError("collection must not be empty")
    if not isinstance(vector_size, int) or isinstance(vector_size, bool) or vector_size < 1:
        raise ValueError("vector_size must be a positive integer")

    indexes = _validated_indexes(specification)

    created_collection = not client.collection_exists(collection)
    if created_collection:
        client.create_collection(collection, vector_size=vector_size)
        existing_schema: dict[str, Any] = {}
    else:
        metadata = client.get_collection(collection)
        try:
            dense = metadata["config"]["params"]["vectors"]["dense"]
            actual_size = dense["size"]
            actual_distance = dense["distance"]
        except (KeyError, TypeError) as exc:
            raise QdrantProvisionError(
                f"existing collection {collection!r} has no valid named dense vector"
            ) from exc
        if type(actual_size) is not int or actual_size != vector_size:
            raise QdrantProvisionError(
                f"existing collection {collection!r} has dense vector size "
                f"{actual_size!r}; requested {vector_size}"
            )
        if actual_distance != "Cosine":
            raise QdrantProvisionError(
                f"existing collection {collection!r} has dense distance "
                f"{actual_distance!r}; required 'Cosine'"
            )
        schema = metadata.get("payload_schema")
        if not isinstance(schema, dict):
            raise QdrantProvisionError(
                f"existing collection {collection!r} has malformed payload_schema"
            )
        existing_schema = schema

    for index in indexes:
        field_name = index["field_name"]
        if field_name not in existing_schema:
            continue
        entry = existing_schema[field_name]
        expected_schema = index["field_schema"]
        expected_type = (
            expected_schema if isinstance(expected_schema, str) else expected_schema["type"]
        )
        if not isinstance(entry, dict) or entry.get("data_type") != expected_type:
            raise QdrantProvisionError(
                f"existing payload index {field_name!r} is incompatible with "
                f"required type {expected_type!r}"
            )
        if isinstance(expected_schema, dict) and expected_schema.get("is_tenant") is True:
            params = entry.get("params")
            if not isinstance(params, dict) or params.get("is_tenant") is not True:
                raise QdrantProvisionError(
                    f"existing payload index {field_name!r} must declare is_tenant=true"
                )
        else:
            params = entry.get("params")
            if isinstance(params, dict) and params.get("is_tenant") is True:
                raise QdrantProvisionError(
                    f"existing payload index {field_name!r} must not declare "
                    "is_tenant=true"
                )

    created_indexes: list[str] = []
    for index in indexes:
        field_name = index["field_name"]
        if field_name in existing_schema:
            continue
        client.create_payload_index(collection, field_name, index["field_schema"])
        created_indexes.append(field_name)

    verify_collection_ready(client, collection)
    return {
        "collection": collection,
        "collection_created": created_collection,
        "indexes_created": created_indexes,
        "ready": True,
    }
