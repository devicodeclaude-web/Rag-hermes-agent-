from __future__ import annotations

from typing import Any

from .acl import AuthorizationContext


def _match(key: str, value: Any) -> dict[str, Any]:
    return {"key": key, "match": {"value": value}}


def build_qdrant_filter(
    context: AuthorizationContext | None,
) -> dict[str, Any]:
    if context is None:
        raise ValueError("authorization context is required")

    access_should: list[dict[str, Any]] = [
        _match("visibility", "public"),
        _match("owner_id", context.user_id),
        {"key": "allowed_user_ids", "match": {"any": [context.user_id]}},
    ]
    if context.groups:
        access_should.append(
            {"key": "allowed_group_ids", "match": {"any": list(context.groups)}}
        )

    private_access = access_should[1:]
    tenant_private = {
        "must": [
            _match("tenant_id", context.tenant_id),
            _match("visibility", "private"),
        ],
        "min_should": {"conditions": private_access, "min_count": 1},
    }
    tenant_public = {
        "must": [
            _match("tenant_id", context.tenant_id),
            _match("visibility", "public"),
        ]
    }
    global_public = {
        "must": [
            _match("tenant_id", "public"),
            _match("visibility", "public"),
        ]
    }
    tenant_branches = [tenant_private, tenant_public, global_public]

    return {
        "must": [
            {"key": "classification", "range": {"lte": context.clearance}},
            _match("tombstone", False),
        ],
        "min_should": {"conditions": tenant_branches, "min_count": 1},
    }
