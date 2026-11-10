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
        if type(document_id) is not str:
            return False, "unknown_document"
        policy = self.policy_for(document_id)
        if policy is None:
            return False, "unknown_document"
        if (
            type(policy.tenant_id) is not str
            or type(policy.visibility) is not str
            or type(policy.owner_id) is not str
            or type(policy.allowed_groups) is not tuple
            or any(type(group) is not str for group in policy.allowed_groups)
            or type(policy.allowed_users) is not tuple
            or any(type(user) is not str for user in policy.allowed_users)
            or type(policy.classification) is not int
            or type(policy.acl_version) is not int
        ):
            raise ValueError("canonical ACL policy has invalid types")
        if type(indexed_acl_version) is not int or indexed_acl_version != policy.acl_version:
            return False, "stale_acl_version"
        if not policy.allows(context):
            return False, "denied"
        return True, "allowed"
