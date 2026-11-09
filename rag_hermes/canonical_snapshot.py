"""Source documentaire locale épinglée, indépendante de l'index Qdrant."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

from .acl_authority import AclPolicy, CanonicalAclAuthority
from .dataset import load_documents_payload
from .ingestion import Document

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class PinnedDocumentSnapshot:
    documents: Mapping[str, Document]
    file_sha256: str

    def source(self, document_id: str) -> Document | None:
        return self.documents.get(document_id)

    def authority(self) -> CanonicalAclAuthority:
        return CanonicalAclAuthority({
            identifiant: AclPolicy(
                tenant_id=doc.tenant_id,
                visibility=doc.visibility,
                owner_id=doc.owner_id,
                allowed_groups=doc.allowed_groups,
                allowed_users=doc.allowed_users,
                classification=doc.classification,
                acl_version=doc.acl_version,
            ) for identifiant, doc in self.documents.items()
        })


def load_pinned_document_snapshot(path: Path, *, expected_sha256: str) -> PinnedDocumentSnapshot:
    """Lire une fois un JSONL et refuser les octets non épinglés avant de l'analyser.

    L'appelant doit obtenir expected_sha256 d'une autorité distincte du fichier.
    Cette fonction ne certifie pas cette origine ni l'absence d'écriture ultérieure.
    """
    if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
        raise ValueError("invalid pinned document digest")
    payload = path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise ValueError("document snapshot digest mismatch")
    documents = load_documents_payload(payload)
    if not documents:
        raise ValueError("empty canonical document snapshot")
    by_id: dict[str, Document] = {}
    for document in documents:
        if document.document_id in by_id:
            raise ValueError("duplicate canonical document id")
        by_id[document.document_id] = document
    return PinnedDocumentSnapshot(MappingProxyType(by_id), actual)
