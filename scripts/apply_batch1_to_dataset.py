#!/usr/bin/env python3
"""Intègre le lot 1 (LLM-écrit, revu) au dataset-v2 JSONL — statut HONNÊTE en attente.

- Lit data/review/dataset-human-authored-batch1.csv, ne prend QUE les lignes
  question+author remplies (20 ; 017/019/020 rejetés ont author vidé -> ignorés).
- Provenance par cas depuis la colonne `author` :
  * 010 = texte écrit par l'humain -> authorship=human_drafted_pending_independent_review,
    provenance_detail=devicodeclaude-web ;
  * tous les autres -> authorship=scaffold_assisted_llm_written,
    provenance_detail = valeur de `author` (claude_written / user_llm_draft /
    user_llm_draft_claude_reworded).
- Statuts honnêtes : la revue est assistée LLM, NON indépendante
  -> manual_review_status=llm_assisted_review_done_pending_independent_validation,
     decision_reference_status=pending_independent_human_validation.
- multi_hop = len(relevant_document_ids) > 1 (aucun cas ne requiert >1 doc -> false).
- Règle no_answer : relevant vide <=> category == no_answer (vérifiée).

Lancer : PYTHONPATH=. /root/work/venv/bin/python scripts/apply_batch1_to_dataset.py
"""
import csv
import json
import sys

CSV = "data/review/dataset-human-authored-batch1.csv"
DATASET = "data/benchmark/dataset-v2.jsonl"
REVIEW_DATE = "2026-10-26"
HUMAN_WRITTEN = {"v3-010"}  # texte final rédigé par l'humain


def split_ids(cell):
    cell = cell.strip()
    return [x.strip() for x in cell.split(";") if x.strip()] if cell else []


def main():
    rows = [
        r
        for r in csv.DictReader(open(CSV, encoding="utf-8"))
        if r.get("question", "").strip() and r.get("author", "").strip()
    ]
    existing = [json.loads(l) for l in open(DATASET, encoding="utf-8") if l.strip()]
    existing_ids = {r.get("case_id") for r in existing}

    new = []
    for r in rows:
        cid = r["case_id"].strip()
        if cid in existing_ids:
            sys.exit(f"ERREUR: case_id déjà présent: {cid}")
        cat = r["category"].strip()
        rel = split_ids(r["relevant_document_ids"])
        dis = split_ids(r["distractor_document_ids"])
        # règle no_answer
        if (len(rel) == 0) != (cat == "no_answer"):
            sys.exit(f"ERREUR no_answer pour {cid}: relevant={rel} cat={cat}")
        drafter = r["author"].strip()
        if cid in HUMAN_WRITTEN:
            authorship = "human_drafted_pending_independent_review"
            provenance = "devicodeclaude-web"
        else:
            authorship = "scaffold_assisted_llm_written"
            provenance = drafter
        rec = {
            "acl_probe": False,
            "authorship": authorship,
            "case_id": cid,
            "category": cat,
            "decision_reference_status": "pending_independent_human_validation",
            "distractor_document_ids": dis,
            "distractor_miner": "handpicked_batch1",
            "manual_review_status": "llm_assisted_review_done_pending_independent_validation",
            "multi_hop": len(rel) > 1,
            "provenance_detail": provenance,
            "question": r["question"].strip(),
            "relevant_document_ids": rel,
            "review_decision": "validate",
            "review_note": (
                f"rédaction: {provenance}; validation: approbation devicodeclaude-web "
                f"({REVIEW_DATE}) revue assistée LLM — NON indépendante; lot batch1"
            ),
        }
        new.append(rec)

    with open(DATASET, "a", encoding="utf-8") as f:
        for rec in new:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"intégrés: {len(new)} (attendu 20)")
    print(f"total dataset: {len(existing) + len(new)}")
    from collections import Counter
    print("catégories ajoutées:", dict(Counter(r["category"] for r in new)))


if __name__ == "__main__":
    main()
