from __future__ import annotations

from typing import Any

from .acl import AuthorizationContext


def reference_allows(payload: dict[str, Any], context: AuthorizationContext) -> bool:
    """Fail-closed ACL oracle independent of the Qdrant filter builder."""
    required = ("tenant_id", "visibility", "classification", "tombstone")
    if any(payload.get(key) is None for key in required):
        return False
    if payload["tombstone"] is not False:
        return False
    try:
        if int(payload["classification"]) > context.clearance:
            return False
    except (TypeError, ValueError):
        return False

    tenant_id = payload["tenant_id"]
    visibility = payload["visibility"]
    if tenant_id == "public":
        return visibility == "public"
    if tenant_id != context.tenant_id:
        return False
    if visibility == "public":
        return True
    if visibility != "private":
        return False
    if payload.get("owner_id") == context.user_id:
        return True
    users = payload.get("allowed_user_ids")
    if isinstance(users, list) and context.user_id in users:
        return True
    groups = payload.get("allowed_group_ids")
    return isinstance(groups, list) and bool(set(groups).intersection(context.groups))
