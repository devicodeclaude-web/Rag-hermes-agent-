#!/usr/bin/env python3
"""Triage QA d'un dataset d'évaluation RAG (format JSONL du dépôt).

Contrôles de structure (toujours) :
- champs requis présents ; `category` dans l'ensemble autorisé ;
- `case_id` uniques ;
- `no_answer` => `relevant_document_ids` vide ; autres catégories => non vide ;
- `multi_hop` cohérent avec le nombre de documents pertinents ;
- rapport des effectifs par catégorie.

Contrôles dépendants du corpus (sauf --structure-only) :
- chaque document pertinent / distracteur existe dans le corpus ;
- aucune fuite de titre (réutilise scripts/check_title_leak.py).

Usage :
    PYTHONPATH=. python3 scripts/check_dataset_qa.py --dataset data/benchmark/dataset-v2.jsonl
    PYTHONPATH=. python3 scripts/check_dataset_qa.py --dataset <f> --structure-only

Sort 1 si au moins un contrôle échoue.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = [
    ROOT / "data/generated/hermes_public_documents.jsonl",
    ROOT / "data/fixtures/private_and_synthetic_documents.jsonl",
    ROOT / "data/fixtures/contradiction_documents.jsonl",
    ROOT / "data/fixtures/injection_documents.jsonl",
]
ALLOWED_CATEGORIES = {"simple", "paraphrase", "close_distractor", "chunk_boundary", "no_answer"}
REQUIRED_FIELDS = {"case_id", "category", "question", "relevant_document_ids", "distractor_document_ids"}

_spec = importlib.util.spec_from_file_location("check_title_leak", ROOT / "scripts" / "check_title_leak.py")
assert _spec is not None and _spec.loader is not None
_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guard)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--corpus", action="append", default=None)
    parser.add_argument("--structure-only", action="store_true")
    args = parser.parse_args()

    cases = load_jsonl(Path(args.dataset))
    errors: list[str] = []

    # --- structure ---
    seen_ids: set[str] = set()
    for case in cases:
        cid = case.get("case_id", "<no id>")
        missing = REQUIRED_FIELDS - set(case)
        if missing:
            errors.append(f"{cid}: champs manquants {sorted(missing)}")
            continue
        if case["category"] not in ALLOWED_CATEGORIES:
            errors.append(f"{cid}: catégorie invalide '{case['category']}'")
        if cid in seen_ids:
            errors.append(f"{cid}: case_id dupliqué")
        seen_ids.add(cid)
        relevant = case["relevant_document_ids"] or []
        if case["category"] == "no_answer":
            if relevant:
                errors.append(f"{cid}: no_answer ne doit pas avoir de document pertinent")
        elif not relevant:
            errors.append(f"{cid}: catégorie '{case['category']}' sans document pertinent")
        if "multi_hop" in case and bool(case["multi_hop"]) != (len(relevant) > 1):
            errors.append(f"{cid}: multi_hop={case['multi_hop']} incohérent avec {len(relevant)} docs pertinents")

    counts = Counter(c.get("category") for c in cases)
    print(f"dataset={args.dataset}")
    print(f"cas={len(cases)} uniques={len(seen_ids)}")
    print(f"par catégorie={dict(counts)}")

    # --- corpus-dependent ---
    if not args.structure_only:
        corpus = [Path(p) for p in args.corpus] if args.corpus else DEFAULT_CORPUS
        known: set[str] = set()
        titles = _guard.load_titles(corpus)
        for path in corpus:
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        known.add(json.loads(line)["document_id"])
        for case in cases:
            for field in ("relevant_document_ids", "distractor_document_ids"):
                for doc_id in case.get(field) or []:
                    if doc_id not in known:
                        errors.append(f"{case.get('case_id')}: {field} introuvable dans le corpus: {doc_id}")
        leaks = 0
        for case in cases:
            qtok = _guard.tokens(case.get("question", ""))
            for doc_id in case.get("relevant_document_ids") or []:
                if _guard.is_contiguous_sublist(_guard.tokens(titles.get(doc_id, "")), qtok):
                    leaks += 1
                    errors.append(f"{case.get('case_id')}: fuite de titre ({doc_id})")
        print(f"fuites_de_titre={leaks}")

    if errors:
        print(f"\nÉCHEC QA ({len(errors)}):")
        for e in errors:
            print("  -", e)
        return 1
    print("\nQA OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
