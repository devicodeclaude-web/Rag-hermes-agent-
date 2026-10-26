#!/usr/bin/env python3
"""Applique la revue indépendante des 32 cas v2+ au JSONL dataset-v2.

Lit la grille de revue (data/review/dataset-v2plus-review-grid.csv), applique au
dataset :
  - validate : question inchangée ;
  - rewrite  : question remplacée par le texte final (extrait de la colonne notes,
               entre « … ») ;
  - cas spécial v2p-015 : gold -> cron-script-only.md, distracteur -> automate-with-cron.md ;
  - recalcule multi_hop = (len(relevant_document_ids) > 1) ; AUCUN cas v2+ ne requiert
    réellement >1 doc (chunk_boundary = 1 doc / 2 chunks) -> false partout, cohérent ;
  - conserve authorship (scaffold_assisted_llm_written) + provenance_detail d'origine ;
  - ajoute review_decision + review_note (rédaction initiale / auteur reformulation
    finale relevé depuis le texte retenu / nature de la validation) ;
  - statuts HONNÊTES : l'approbation est une revue assistée LLM, PAS une validation
    humaine indépendante -> aucun statut ne prétend l'indépendance.

Lancer : PYTHONPATH=. /root/work/venv/bin/python scripts/apply_review_v2plus.py
"""
import csv
import json
import re
import sys

GRID = "data/review/dataset-v2plus-review-grid.csv"
DATASET = "data/benchmark/dataset-v2.jsonl"
REVIEW_DATE = "2026-10-26"

# Auteur du TEXTE FINAL retenu (relevé depuis le texte réellement intégré).
# 004 et 007 : le texte final a été rédigé par le LLM (claude), approuvé par l'humain.
# 010/011/015/021/027 : le texte final a été rédigé par l'humain.
FINAL_TEXT_AUTHOR = {
    "v2p-004": "claude_llm",
    "v2p-007": "claude_llm",
    "v2p-010": "devicodeclaude-web",
    "v2p-011": "devicodeclaude-web",
    "v2p-015": "devicodeclaude-web",
    "v2p-021": "devicodeclaude-web",
    "v2p-027": "devicodeclaude-web",
}

# v2p-015 : changement de gold / distracteur décidé en revue.
DOC_OVERRIDE = {
    "v2p-015": {
        "relevant_document_ids": ["hermes-agent:guides/cron-script-only.md"],
        "distractor_document_ids": ["hermes-agent:guides/automate-with-cron.md"],
    },
}

MANUAL_STATUS = "llm_assisted_review_done_pending_independent_validation"
DECISION_STATUS = "pending_independent_human_validation"


def extract_reformulation(note):
    m = re.search(r"reformulée.*?:\s*«\s*(.+?)\s*»", note, re.S)
    return m.group(1).strip() if m else None


def main():
    grid = {
        r["case_id"].strip(): r
        for r in csv.DictReader(open(GRID, encoding="utf-8-sig"))
        if str(r.get("case_id", "")).startswith("v2p-")
    }
    rows = [json.loads(l) for l in open(DATASET, encoding="utf-8") if l.strip()]

    touched = 0
    for rec in rows:
        cid = rec.get("case_id", "")
        if not str(cid).startswith("v2p-"):
            continue
        g = grid.get(cid)
        if not g:
            sys.exit(f"ERREUR: {cid} absent de la grille")
        decision = g["reviewer_decision"].strip()
        if decision not in ("validate", "rewrite"):
            sys.exit(f"ERREUR: décision inattendue pour {cid}: {decision!r}")

        # question
        if decision == "rewrite":
            q = extract_reformulation(g["notes"])
            if not q:
                sys.exit(f"ERREUR: reformulation introuvable pour {cid}")
            rec["question"] = q
            final_author = FINAL_TEXT_AUTHOR.get(cid, "?")
        else:
            final_author = "n/a (texte inchangé)"

        # overrides doc (015)
        if cid in DOC_OVERRIDE:
            for k, v in DOC_OVERRIDE[cid].items():
                rec[k] = v

        # multi_hop selon définition (besoin réel >1 doc). Ici aucun cas ne requiert
        # >1 doc -> aligné sur len(relevant)>1.
        rec["multi_hop"] = len(rec.get("relevant_document_ids", [])) > 1

        # provenance conservée ; statuts honnêtes ; note de revue
        rec["review_decision"] = decision
        rec["manual_review_status"] = MANUAL_STATUS
        rec["decision_reference_status"] = DECISION_STATUS
        rec["review_note"] = (
            f"rédaction initiale: {rec.get('provenance_detail', '?')}; "
            f"reformulation finale: {final_author}; "
            f"validation: approbation devicodeclaude-web ({REVIEW_DATE}) au cours d'une "
            f"revue assistée LLM — NON indépendante (réviseur non indépendant du scaffolding)"
        )
        touched += 1

    with open(DATASET, "w", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"cas v2+ traités: {touched} (attendu 32)")
    print(f"total dataset: {len(rows)}")


if __name__ == "__main__":
    main()
