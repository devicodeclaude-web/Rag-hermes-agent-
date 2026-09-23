from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .acl import AuthorizationContext


@dataclass(frozen=True)
class AclPolicy:
    tenant_id: str
    visibility: str
    owner_id: str
    allowed_groups: tuple[str, ...]
    allowed_users: tuple[str, ...]
    classification: int
    acl_version: int

    def allows(self, context: AuthorizationContext) -> bool:
        if self.classification > context.clearance:
            return False
        if self.tenant_id == "public":
            return self.visibility == "public"
        if self.tenant_id != context.tenant_id:
            return False
        if self.visibility == "public":
            return True
        if self.visibility != "private":
            return False
        return (
            self.owner_id == context.user_id
            or context.user_id in self.allowed_users
            or bool(set(self.allowed_groups).intersection(context.groups))
        )


class CanonicalAclAuthority:
    """Canonical local registry; Qdrant ACL payloads are only derived indexes."""

    def __init__(self, policies: Mapping[str, AclPolicy]):
        self._policies = dict(policies)

    def policy_for(self, document_id: str) -> AclPolicy | None:
        return self._policies.get(document_id)

    def authorize(
        self, document_id: str, indexed_acl_version: object, context: AuthorizationContext
    ) -> tuple[bool, str]:
        policy = self.policy_for(document_id)
        if policy is None:
            return False, "unknown_document"
        if indexed_acl_version != policy.acl_version:
            return False, "stale_acl_version"
        if not policy.allows(context):
            return False, "denied"
        return True, "allowed"
