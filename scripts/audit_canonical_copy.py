#!/usr/bin/env python3
"""Audit en lecture seule une copie canonique face à une collection Qdrant.

Arrêter tous les écrivains avant l'audit. Le digest de l'ancre doit provenir
D'UNE SOURCE INDÉPENDANTE de la copie ; un succès n'autorise pas le redémarrage.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from rag_hermes.canonical_reconciliation import audit_canonical_copy_index
from rag_hermes.qdrant_identity import _check, QUERY_ACCESS
from rag_hermes.qdrant_rest import QdrantAuditClient
from rag_hermes.token_chunking_profile import LockedTokenChunker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--copy", type=Path, required=True)
    parser.add_argument("--anchor-sha256", required=True,
                        help="empreinte approuvée indépendamment, jamais calculée depuis la copie")
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--tokenizer-lock", type=Path, required=True)
    parser.add_argument("--tokenizer-file", type=Path, required=True)
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()
    try:
        # An admin or points-write token must never be loaded into this tool.
        token = os.environ.get("RAG_QDRANT_G1_AUDIT_API_KEY", "")
        _check(
            token,
            collection=args.collection,
            expected=QUERY_ACCESS,
        )
        chunker = LockedTokenChunker(
            lock_path=args.tokenizer_lock, tokenizer_path=args.tokenizer_file,
        )
        client = QdrantAuditClient(args.qdrant_url, api_key=token)
        report = audit_canonical_copy_index(
            args.copy, anchor_sha256=args.anchor_sha256, client=client,
            collection=args.collection, chunker=chunker, page_size=args.page_size,
        )
    except Exception as exc:
        # A transport cause can contain a URL or response body: no exception
        # text, repr, traceback or credential is printed to stdout/stderr here.
        print(f"REFUS : {type(exc).__name__} ; aucune réparation effectuée")
        return 2
    print(f"Concordance observée : {report.point_count} points, payload {report.payload_sha256}.")
    print("Lecture seule ; ne pas redémarrer sans revue et plan de réconciliation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
