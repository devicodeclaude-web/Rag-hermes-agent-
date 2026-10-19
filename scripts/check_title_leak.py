#!/usr/bin/env python3
"""Garde anti-fuite-de-titre pour les datasets d'évaluation RAG.

Règle (issue de la revue humaine du dataset v1) : une question ne doit pas
contenir le titre de son document cible mot pour mot. Sinon on mesure un match
lexical de titre, pas du retrieval sémantique.

Pour chaque cas ayant des `relevant_document_ids`, on compare la suite de tokens
du titre du document cible à la suite de tokens de la question. Si le titre
apparaît comme sous-séquence CONTIGUË de la question, c'est une fuite.

Usage :
    PYTHONPATH=. python3 scripts/check_title_leak.py \
        --dataset data/benchmark/dataset-v1.jsonl

Sort 1 s'il reste au moins une fuite (sauf --report-only).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = [
    ROOT / "data/generated/hermes_public_documents.jsonl",
    ROOT / "data/fixtures/private_and_synthetic_documents.jsonl",
]
FRONTMATTER_TITLE = re.compile(r"^title:\s*\"?(.*?)\"?\s*$", re.MULTILINE)
H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def document_title(content: str) -> str:
    head = content[:800]
    match = FRONTMATTER_TITLE.search(head)
    if match and match.group(1).strip():
        return match.group(1).strip()
    match = H1.search(content)
    return match.group(1).strip() if match else ""


def load_titles(corpus_files: list[Path]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for path in corpus_files:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            titles[record["document_id"]] = document_title(record.get("content", ""))
    return titles


def is_contiguous_sublist(needle: list[str], haystack: list[str]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    for start in range(len(haystack) - len(needle) + 1):
        if haystack[start : start + len(needle)] == needle:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "data/benchmark/dataset-v1.jsonl"))
    parser.add_argument("--corpus", action="append", default=None)
    parser.add_argument("--report-only", action="store_true", help="n'échoue jamais")
    args = parser.parse_args()

    corpus = [Path(p) for p in args.corpus] if args.corpus else DEFAULT_CORPUS
    titles = load_titles(corpus)
    cases = [
        json.loads(line)
        for line in Path(args.dataset).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    leaks: list[tuple[str, str, str]] = []
    checked = 0
    for case in cases:
        question_tokens = tokens(case.get("question", ""))
        for doc_id in case.get("relevant_document_ids", []) or []:
            checked += 1
            title = titles.get(doc_id, "")
            if title and is_contiguous_sublist(tokens(title), question_tokens):
                leaks.append((case["case_id"], doc_id, title))

    total = len(cases)
    print(f"dataset={args.dataset}")
    print(f"cas={total} cibles_vérifiées={checked} fuites={len(leaks)}")
    for case_id, doc_id, title in leaks:
        print(f"  FUITE {case_id}: titre « {title} » présent dans la question (cible {doc_id})")
    if leaks and not args.report_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
