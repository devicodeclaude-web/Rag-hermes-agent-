#!/usr/bin/env python3
"""Audit ou plan en lecture seule d'une copie canonique face à une collection Qdrant.

Arrêter tous les écrivains avant l'audit. Le digest de l'ancre doit provenir
D'UNE SOURCE INDÉPENDANTE de la copie ; un succès n'autorise pas le redémarrage.

`--plan` énumère les divergences pour qu'un humain décide de la réparation.
La sortie ne montre que les noms des champs canoniques ; les clés inconnues
sont comptées sans être imprimées (elles peuvent contenir un secret). Le plan
en mémoire ne doit pas être journalisé tel quel. Un plan vide n'est pas une
preuve de concordance : seul l'audit en est la porte.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from rag_hermes.canonical_reconciliation import (
    audit_canonical_copy_index, plan_canonical_index_reconciliation,
    render_divergence_report,
)
from rag_hermes.qdrant_identity import _check, QUERY_ACCESS
from rag_hermes.qdrant_rest import QdrantAuditClient
from rag_hermes.token_chunking_profile import LockedTokenChunker


def _print_plan(plan) -> None:
    # Point IDs come from the index and need sanitising. Unknown payload
    # field names may be secrets even when printable: the renderer prints
    # only canonical field names and counts all unknown keys.
    for line in render_divergence_report(plan):
        print(line)


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
    parser.add_argument("--plan", action="store_true",
                        help="énumérer les divergences au lieu de rendre un verdict d'audit")
    parser.add_argument("--surplus-budget", type=int, default=1000,
                        help="plafond du nombre TOTAL de points lus "
                             "(attendus + surplus) ; borne mémoire, pas un "
                             "plafond du nombre d'intrus énumérés")
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
        if args.plan:
            plan = plan_canonical_index_reconciliation(
                args.copy, anchor_sha256=args.anchor_sha256, client=client,
                collection=args.collection, chunker=chunker,
                page_size=args.page_size, surplus_budget=args.surplus_budget,
            )
        else:
            report = audit_canonical_copy_index(
                args.copy, anchor_sha256=args.anchor_sha256, client=client,
                collection=args.collection, chunker=chunker, page_size=args.page_size,
            )
    except Exception as exc:
        # A transport cause can contain a URL or response body: no exception
        # text, repr, traceback or credential is printed to stdout/stderr here.
        print(f"REFUS : {type(exc).__name__} ; aucune réparation effectuée")
        return 2
    if args.plan:
        _print_plan(plan)
        print("Lecture seule : rien n'a été réparé. Décider la réparation, l'appliquer")
        print("hors ligne, puis relancer l'audit (un plan vide n'est pas une preuve).")
        # Code distinct : une divergence n'est ni un succès ni une panne.
        return 0 if plan.is_clean else 1
    print(f"Concordance observée : {report.point_count} points, payload {report.payload_sha256}.")
    print("Lecture seule ; ne pas redémarrer sans revue et plan de réconciliation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
