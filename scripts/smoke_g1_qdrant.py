"""Essai d'intégration sur Qdrant local : audit paginé et ACL altérée.

Démarrer Qdrant sur 127.0.0.1:16333 puis :
    PYTHONPATH=. python scripts/smoke_g1_qdrant.py
Une collection temporaire unique est créée puis supprimée ; aucune collection
préexistante n'est touchée. Ce n'est pas un test de campagne de production.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from rag_hermes.acl import AuthorizationContext
from rag_hermes.canonical_snapshot import load_pinned_document_snapshot
from rag_hermes.g1_wiring import build_audited_g1_service

from rag_hermes.index_integrity import audit_qdrant_index, verify_index_snapshot
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_rest import QdrantAuditRestClient, QdrantRestClient
from rag_hermes.qdrant_store import chunk_to_point


def document(identifiant: str, contenu: str) -> Document:
    return Document(
        document_id=identifiant, content=contenu, tenant_id="alpha",
        visibility="private", owner_id="alice", allowed_groups=(),
        allowed_users=(), classification=1, doc_version=1,
        source_uri=f"file:///docs/{identifiant}.md",
    )


def main() -> None:
    url = "http://127.0.0.1:16333"
    collection = f"hermes_g1_audit_smoke_{uuid4().hex}"
    client = QdrantRestClient(url)
    auditor = QdrantAuditRestClient(url)
    chunks = [
        chunk_document(document("a", "Source A"))[0],
        chunk_document(document("b", "Source B"))[0],
    ]
    points = [chunk_to_point(chunk, [1.0]) for chunk in chunks]
    # L'empreinte provient des documents de cet essai, jamais du scroll Qdrant.
    pinned = verify_index_snapshot(chunks, points).payload_sha256
    created = False
    try:
        if client.collection_exists(collection):
            raise RuntimeError("collision de nom : ne pas toucher cette collection")
        client.create_collection(collection, vector_size=1)
        created = True
        client.upsert(collection, points)
        report = audit_qdrant_index(
            auditor, collection, chunks, expected_manifest_sha256=pinned,
            page_size=1,
        )
        if report.point_count != 2 or report.payload_sha256 != pinned:
            raise AssertionError("l'audit initial a échoué")
        with TemporaryDirectory(prefix="hermes-g1-docs-") as directory:
            source = Path(directory) / "documents.jsonl"
            source.write_text(
                "".join(json.dumps(asdict(doc), ensure_ascii=False) + "\n"
                        for doc in (document("a", "Source A"), document("b", "Source B"))),
                encoding="utf-8",
            )
            snapshot = load_pinned_document_snapshot(
                source, expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            )
            service, audited = build_audited_g1_service(
                snapshot=snapshot, expected_manifest_sha256=pinned,
                audit_client=auditor, query_client=client, collection=collection,
                chunker=chunk_document, embed=lambda text: [1.0],
                generator=lambda question, evidence: "Source A [S1].",
            )
            answer = service.answer(
                "Source A", context=AuthorizationContext("alpha", "alice", (), 1),
            )
            if audited.point_count != 2 or answer.abstained or not answer.citations:
                raise AssertionError("réponse citée sur Qdrant réel absente")
        forged = deepcopy(points[0])
        forged["payload"]["owner_id"] = "bob"
        client.upsert(collection, [forged])
        try:
            audit_qdrant_index(
                auditor, collection, chunks, expected_manifest_sha256=pinned,
                page_size=1,
            )
        except ValueError as exc:
            if "payload conflicts" not in str(exc):
                raise
        else:
            raise AssertionError("ACL falsifiée non détectée")
        print("Qdrant réel OK : audit paginé, réponse citée, ACL falsifiée détectée")
    finally:
        if created:
            client.delete_collection(collection)


if __name__ == "__main__":
    main()
