from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any

from .acl import AuthorizationContext
from .acl_authority import AclPolicy, CanonicalAclAuthority
from .acl_reference import reference_allows

CATEGORIES = (
    "cross_tenant",
    "groups",
    "named_users",
    "clearance_insufficient",
    "clearance_sufficient",
    "acl_missing_or_null",
    "revoked_right",
    "stale_acl_version",
    "public_visibility",
)


@dataclass(frozen=True)
class MatrixScenario:
    category: str
    trial: int
    context: AuthorizationContext
    payload: dict[str, Any]
    authority_policy: AclPolicy
    index_reference_allows: bool
    authority_allows: bool


def build_scenario(category: str, trial: int, rng: random.Random) -> MatrixScenario:
    if category not in CATEGORIES:
        raise ValueError(f"unknown ACL matrix category: {category}")
    tenant = f"tenant-{category}-{trial}"
    document_id = f"{category}-{trial:03d}"
    context = AuthorizationContext(tenant, "alice", ("admins",), 2)
    payload: dict[str, Any] = {
        "document_id": document_id,
        "text": f"ACL matrix {category} trial {trial}",
        "tenant_id": tenant,
        "visibility": "private",
        "owner_id": "alice",
        "allowed_user_ids": [],
        "allowed_group_ids": [],
        "classification": 2,
        "tombstone": False,
        "acl_version": 2,
    }
    policy = AclPolicy(tenant, "private", "alice", (), (), 2, 2)

    if category == "cross_tenant":
        payload["tenant_id"] = f"foreign-{trial}"
        policy = AclPolicy(f"foreign-{trial}", "private", "alice", (), (), 2, 2)
    elif category == "groups":
        group = "admins" if trial % 2 == 0 else "auditors"
        payload.update(owner_id="bob", allowed_group_ids=[group])
        policy = AclPolicy(tenant, "private", "bob", (group,), (), 2, 2)
    elif category == "named_users":
        user = "alice" if trial % 2 == 0 else "charlie"
        payload.update(owner_id="bob", allowed_user_ids=[user])
        policy = AclPolicy(tenant, "private", "bob", (), (user,), 2, 2)
    elif category == "clearance_insufficient":
        payload["classification"] = 3
        policy = AclPolicy(tenant, "private", "alice", (), (), 3, 2)
    elif category == "clearance_sufficient":
        classification = rng.randint(0, 2)
        payload["classification"] = classification
        policy = AclPolicy(tenant, "private", "alice", (), (), classification, 2)
    elif category == "acl_missing_or_null":
        field = rng.choice(("visibility", "classification", "tombstone"))
        if trial % 2:
            payload.pop(field)
        else:
            payload[field] = None
    elif category == "revoked_right":
        payload.update(acl_version=1, owner_id="alice")
        policy = AclPolicy(tenant, "private", "bob", (), (), 2, 2)
    elif category == "stale_acl_version":
        payload["acl_version"] = 1
    elif category == "public_visibility":
        payload.update(tenant_id="public", visibility="public", owner_id="docs", classification=0)
        policy = AclPolicy("public", "public", "docs", (), (), 0, 2)

    authority = CanonicalAclAuthority({document_id: policy})
    authority_allowed, _ = authority.authorize(
        document_id, payload.get("acl_version"), context
    )
    return MatrixScenario(
        category=category,
        trial=trial,
        context=context,
        payload=payload,
        authority_policy=policy,
        index_reference_allows=reference_allows(payload, context),
        authority_allows=authority_allowed,
    )
