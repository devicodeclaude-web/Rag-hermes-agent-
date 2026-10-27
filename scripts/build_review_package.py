#!/usr/bin/env python3
"""Construit un paquet de revue humaine enrichi pour le dataset v1.

Pour chaque cas du jeu de 100 questions, on résout les identifiants de documents
(pertinents proposés et distracteurs BM25) vers un extrait de texte lisible, afin
qu'un réviseur humain puisse décider SANS ouvrir les JSONL ni voir aucun score
BGE-M3 / reranker (interdits par `docs/dataset-v1-review-guide.md`).

Sorties (déterministes, régénérables) :
- `data/review/dataset-v1-full-100.csv`   : grille à remplir (colonnes réviseur vides)
- `data/review/dataset-v1-review-package.md` : dossier lisible avec extraits

Aucune donnée n'est marquée comme validée ; ce script prépare la revue, il ne la
remplace pas.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/benchmark/dataset-v1.jsonl"
CORPUS_FILES = [
    ROOT / "data/generated/hermes_public_documents.jsonl",
    ROOT / "data/fixtures/private_and_synthetic_documents.jsonl",
]
OUT_CSV = ROOT / "data/review/dataset-v1-full-100.csv"
OUT_MD = ROOT / "data/review/dataset-v1-review-package.md"

EXCERPT_CHARS = 700
FRONTMATTER = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
TITLE_RE = re.compile(r"^title:\s*\"?(.*?)\"?\s*$", re.MULTILINE)


def load_corpus() -> dict[str, dict]:
    docs: dict[str, dict] = {}
    for path in CORPUS_FILES:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                docs[record["document_id"]] = record
    return docs


def title_of(content: str) -> str:
    match = TITLE_RE.search(content[:600])
    return match.group(1).strip() if match else "(sans titre)"


def excerpt_of(content: str) -> str:
    body = FRONTMATTER.sub("", content, count=1).strip()
    body = re.sub(r"\s+", " ", body)
    if len(body) > EXCERPT_CHARS:
        body = body[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " […]"
    return body


def render_doc(doc_id: str, docs: dict[str, dict]) -> tuple[str, str]:
    record = docs.get(doc_id)
    if record is None:
        return "(document introuvable)", ""
    content = record.get("content", "")
    return title_of(content), excerpt_of(content)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--out-csv", default=str(OUT_CSV))
    args = parser.parse_args()
    dataset = Path(args.dataset)
    out_md = Path(args.out_md)
    out_csv = Path(args.out_csv)

    docs = load_corpus()
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases.sort(key=lambda c: c["case_id"])

    missing: set[str] = set()
    md: list[str] = []
    md.append(f"# Paquet de revue humaine — {dataset.stem} ({len(cases)} questions)\n")
    md.append(
        "Généré par `scripts/build_review_package.py`. Règles : lire chaque extrait, "
        "ne consulter aucun score BGE-M3/reranker, ne pas valider une question au seul "
        f"motif que le document contient son titre. Reporte tes décisions dans `{out_csv.name}`. "
        "Un cas `no_answer` est correct si AUCUN document ne répond : vérifie-le sur l'extrait "
        "du distracteur.\n"
    )

    rows: list[dict] = []
    for case in cases:
        cid = case["case_id"]
        category = case["category"]
        question = case["question"]
        relevant = case.get("relevant_document_ids", []) or []
        distractors = case.get("distractor_document_ids", []) or []

        md.append(f"\n---\n\n## {cid} · {category}\n")
        md.append(f"**Question :** {question}\n")

        md.append("\n**Document(s) pertinent(s) proposé(s) :**\n")
        if not relevant:
            md.append("- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)\n")
        for doc_id in relevant:
            title, excerpt = render_doc(doc_id, docs)
            if excerpt == "" and title == "(document introuvable)":
                missing.add(doc_id)
            md.append(f"- `{doc_id}` — **{title}**\n\n  > {excerpt}\n")

        md.append("\n**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**\n")
        for doc_id in distractors:
            title, excerpt = render_doc(doc_id, docs)
            if excerpt == "" and title == "(document introuvable)":
                missing.add(doc_id)
            md.append(f"- `{doc_id}` — **{title}**\n\n  > {excerpt}\n")

        rows.append(
            {
                "case_id": cid,
                "category": category,
                "question": question,
                "proposed_relevant_document_ids": ";".join(relevant),
                "bm25_distractor_document_ids": ";".join(distractors),
                "reviewer_decision": "",
                "corrected_relevant_document_ids": "",
                "reviewer_name": "",
                "review_date_utc": "",
                "notes": "",
            }
        )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    out_md.write_text("".join(md), encoding="utf-8")

    print(f"cases={len(rows)} csv={out_csv} md={out_md}")
    if missing:
        print("DOCUMENTS INTROUVABLES:", sorted(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
