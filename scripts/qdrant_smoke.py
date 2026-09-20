#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rag_hermes.acl import AuthorizationContext
from rag_hermes.dataset import load_documents
from rag_hermes.ingestion import chunk_document
from rag_hermes.qdrant_filter import build_qdrant_filter
from rag_hermes.qdrant_rest import QdrantRestClient
from rag_hermes.qdrant_store import chunk_to_point, deterministic_test_vector


def batches(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default="hermes_chunks_smoke_v1")
    parser.add_argument("--documents", action="append", required=True)
    parser.add_argument("--index-spec", default="qdrant/payload-indexes.json")
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()

    documents = []
    for path in args.documents:
        documents.extend(load_documents(path))
    chunks = [
        chunk
        for document in documents
        for chunk in chunk_document(document, max_tokens=420, overlap_tokens=40)
    ]
    points = [
        chunk_to_point(chunk, deterministic_test_vector(chunk.text, dimensions=8))
        for chunk in chunks
    ]

    client = QdrantRestClient(args.url, timeout=120)
    client.create_collection(args.collection, vector_size=8)
    specification = json.loads(Path(args.index_spec).read_text())
    for index in specification["payload_indexes"]:
        client.create_payload_index(
            args.collection, index["field_name"], index["field_schema"]
        )
    for batch in batches(points, args.batch_size):
        client.upsert(args.collection, batch)

    probes = []
    probe_contexts = [
        (AuthorizationContext("alpha", "alice", ("admins",), 2), "alpha", True),
        (AuthorizationContext("beta", "bob", ("admins",), 2), "beta", True),
        (AuthorizationContext("gamma", "gina", ("admins",), 2), "gamma", True),
        (AuthorizationContext("alpha", "alice", ("admins",), 0), "alpha", False),
    ]
    for context, probe_tenant, expect_private in probe_contexts:
        probe_chunk = next(chunk for chunk in chunks if chunk.tenant_id == probe_tenant)
        probe_vector = deterministic_test_vector(probe_chunk.text, dimensions=8)
        results = client.query(
            args.collection,
            probe_vector,
            query_filter=build_qdrant_filter(context),
            limit=20,
        )
        tenants = sorted({point["payload"]["tenant_id"] for point in results})
        forbidden = [
            tenant for tenant in tenants if tenant not in {context.tenant_id, "public"}
        ]
        if forbidden:
            raise RuntimeError(
                f"ACL leak for {context.tenant_id}: forbidden tenants {forbidden}"
            )
        has_private = context.tenant_id in tenants
        if has_private != expect_private:
            raise RuntimeError(
                f"Private access mismatch for {context.tenant_id} at clearance "
                f"{context.clearance}: expected {expect_private}, got {has_private}"
            )
        probes.append(
            {
                "tenant_id": context.tenant_id,
                "clearance": context.clearance,
                "private_access_expected": expect_private,
                "private_access_observed": has_private,
                "returned_tenants": tenants,
                "result_count": len(results),
            }
        )

    print(
        json.dumps(
            {
                "collection": args.collection,
                "documents": len(documents),
                "chunks": len(chunks),
                "vector_kind": "deterministic-test-only-not-an-embedding",
                "leak_count": 0,
                "probes": probes,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
