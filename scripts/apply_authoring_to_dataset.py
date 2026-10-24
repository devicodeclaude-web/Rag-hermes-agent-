#!/usr/bin/env python3
"""Intègre les questions rédigées (humain) depuis un CSV d'authoring vers le dataset v2 JSONL.

Ne traite QUE les lignes dont `question` ET `author` sont renseignés (rédaction
humaine — indépendance). Chaque ligne retenue est validée avant intégration :
- `question` non vide, `author` non vide ;
- `category` dans l'ensemble autorisé ;
- règle no_answer : relevant vide <=> category == no_answer ;
- docs cible/distracteur présents dans le corpus ;
- aucune fuite de titre (réutilise scripts/check_title_leak.py) ;
- case_id unique (vs dataset existant et vs lot courant).

Les lignes intégrées sont écrites avec le schéma du dataset et le statut HONNÊTE
`pending_human_validation` / `pending_initial_control` : une question rédigée par
l'humain reste à passer en revue indépendante avant de compter comme `validated`.

Usage :
    PYTHONPATH=. python3 scripts/apply_authoring_to_dataset.py \
        --authoring data/review/dataset-v2plus-authoring.csv            # dry-run
    PYTHONPATH=. python3 scripts/apply_authoring_to_dataset.py \
        --authoring data/review/dataset-v2plus-authoring.csv --apply    # écrit le JSONL

Sort 1 si une ligne prête échoue à la validation (rien n'est écrit).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/benchmark/dataset-v2.jsonl"
CORPUS = [
    ROOT / "data/generated/hermes_public_documents.jsonl",
    ROOT / "data/fixtures/private_and_synthetic_documents.jsonl",
]
ALLOWED = {"simple", "paraphrase", "close_distractor", "chunk_boundary", "no_answer"}

_spec = importlib.util.spec_from_file_location("check_title_leak", ROOT / "scripts" / "check_title_leak.py")
assert _spec is not None and _spec.loader is not None
_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guard)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def split_ids(cell: str) -> list[str]:
    return [x.strip() for x in (cell or "").replace(";", ",").split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authoring", required=True)
    ap.add_argument("--apply", action="store_true", help="écrit réellement dans le dataset")
    args = ap.parse_args()

    corpus_ids: set[str] = set()
    for p in CORPUS:
        for rec in load_jsonl(p):
            corpus_ids.add(rec["document_id"])
    titles = _guard.load_titles(CORPUS)

    existing = load_jsonl(DATASET)
    existing_ids = {c["case_id"] for c in existing}

    rows = list(csv.DictReader(Path(args.authoring).read_text(encoding="utf-8").splitlines()))
    ready = [r for r in rows if r.get("question", "").strip() and r.get("author", "").strip()]

    errors: list[str] = []
    new_records: list[dict] = []
    batch_ids: set[str] = set()
    for r in ready:
        cid = r["case_id"].strip()
        cat = r["category"].strip()
        q = r["question"].strip()
        rel = split_ids(r.get("relevant_document_ids", ""))
        dis = split_ids(r.get("distractor_document_ids", ""))

        if cid in existing_ids or cid in batch_ids:
            errors.append(f"{cid}: case_id déjà utilisé")
        batch_ids.add(cid)
        if cat not in ALLOWED:
            errors.append(f"{cid}: catégorie invalide '{cat}'")
        if cat == "no_answer" and rel:
            errors.append(f"{cid}: no_answer ne doit pas avoir de doc pertinent")
        if cat != "no_answer" and not rel:
            errors.append(f"{cid}: '{cat}' sans doc pertinent")
        for did in rel + dis:
            if did not in corpus_ids:
                errors.append(f"{cid}: doc introuvable dans le corpus: {did}")
        overlap = set(rel) & set(dis)
        if overlap:
            errors.append(f"{cid}: cible et piège se recoupent: {sorted(overlap)}")
        qtok = _guard.tokens(q)
        for did in rel:
            if _guard.is_contiguous_sublist(_guard.tokens(titles.get(did, "")), qtok):
                errors.append(f"{cid}: fuite de titre ({did})")

        new_records.append({
            "acl_probe": False,
            "case_id": cid,
            "category": cat,
            "decision_reference_status": "pending_human_validation",
            "distractor_document_ids": dis,
            "distractor_miner": "handpicked_review_v2plus",
            "authorship": "human_authored",
            "manual_review_status": "pending_initial_control",
            "question": q,
            "relevant_document_ids": rel,
            "multi_hop": len(rel) > 1,
        })

    print(f"authoring={args.authoring}")
    print(f"lignes_totales={len(rows)} prêtes(question+author)={len(ready)} intégrables={len(new_records)}")
    if errors:
        print(f"\nÉCHEC VALIDATION ({len(errors)}):")
        for e in errors:
            print("  -", e)
        return 1
    if not new_records:
        print("\nRien à intégrer (aucune ligne avec question+author). Remplis le CSV puis relance.")
        return 0
    if args.apply:
        with DATASET.open("a", encoding="utf-8") as f:
            for rec in new_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"\nINTÉGRÉ {len(new_records)} cas -> {DATASET} (total={len(existing)+len(new_records)})")
        print("Lance ensuite les portes : check_title_leak.py + check_dataset_qa.py")
    else:
        print(f"\nDRY-RUN ok : {len(new_records)} cas prêts à intégrer (relance avec --apply).")
        for rec in new_records:
            print(f"  + {rec['case_id']} [{rec['category']}] {rec['question'][:70]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
