#!/usr/bin/env python3
"""Intègre le lot 15 (8 chunk_boundary, revus) au dataset-v2 JSONL — statut en attente.

- Lit data/review/dataset-batch15-chunkboundary.csv (lignes question+author remplies).
- authorship = scaffold_assisted_llm_written (origine scaffold LLM, y compris les
  reformulations humaines d'un brouillon LLM) ; provenance_detail = colonne `author`
  (claude_written / claude_draft_devicodeclaude_reworded).
- Statuts honnêtes NON-indépendants (revue assistée LLM).
- multi_hop = len(relevant) > 1 (chunk_boundary = 1 gold/2 chunks -> multi_hop false).
- Règle no_answer vérifiée (ici aucune : tous chunk_boundary avec 1 gold).

Lancer : PYTHONPATH=. /root/work/venv/bin/python scripts/apply_batch15_to_dataset.py
"""
import csv, json, sys

CSV = "data/review/dataset-batch15-chunkboundary.csv"
DATASET = "data/benchmark/dataset-v2.jsonl"
REVIEW_DATE = "2026-10-26"


def ids(cell):
    cell = cell.strip()
    return [x.strip() for x in cell.split(";") if x.strip()] if cell else []


def main():
    rows = [r for r in csv.DictReader(open(CSV, encoding="utf-8"))
            if r.get("question", "").strip() and r.get("author", "").strip()]
    existing = [json.loads(l) for l in open(DATASET, encoding="utf-8") if l.strip()]
    ex_ids = {r.get("case_id") for r in existing}
    new = []
    for r in rows:
        cid = r["case_id"].strip()
        if cid in ex_ids:
            sys.exit(f"ERREUR: case_id déjà présent: {cid}")
        cat = r["category"].strip()
        rel = ids(r["relevant_document_ids"]); dis = ids(r["distractor_document_ids"])
        if (len(rel) == 0) != (cat == "no_answer"):
            sys.exit(f"ERREUR no_answer {cid}")
        prov = r["author"].strip()
        new.append({
            "acl_probe": False,
            "authorship": "scaffold_assisted_llm_written",
            "case_id": cid,
            "category": cat,
            "decision_reference_status": "pending_independent_human_validation",
            "distractor_document_ids": dis,
            "distractor_miner": "handpicked_batch15",
            "manual_review_status": "llm_assisted_review_done_pending_independent_validation",
            "multi_hop": len(rel) > 1,
            "provenance_detail": prov,
            "question": r["question"].strip(),
            "relevant_document_ids": rel,
            "review_decision": "validate",
            "review_note": (f"rédaction: {prov}; frontière chunk_boundary re-vérifiée (384/64); "
                            f"validation devicodeclaude-web ({REVIEW_DATE}) revue assistée LLM NON indépendante; lot batch15"),
        })
    with open(DATASET, "a", encoding="utf-8") as f:
        for rec in new:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"intégrés: {len(new)} | total: {len(existing)+len(new)}")


if __name__ == "__main__":
    main()
