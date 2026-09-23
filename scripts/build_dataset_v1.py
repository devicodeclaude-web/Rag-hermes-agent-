#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/generated/hermes_public_documents.jsonl"
OUTPUT = ROOT / "data/benchmark/dataset-v1.jsonl"
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
SEED = 20260923


def tokens(text: str) -> list[str]:
    return [item.casefold() for item in TOKEN_RE.findall(text)]


def title(record: dict) -> str:
    for line in record["content"].splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return record["document_id"].rsplit("/", 1)[-1].removesuffix(".md")


def bm25_neighbor(index: int, docs: list[dict], document_frequency: Counter[str]) -> str:
    query = Counter(tokens(title(docs[index])))
    average_length = sum(len(tokens(doc["content"])) for doc in docs) / len(docs)
    best_score = float("-inf")
    best_id = ""
    for candidate_index, candidate in enumerate(docs):
        if candidate_index == index:
            continue
        terms = Counter(tokens(candidate["content"]))
        length = sum(terms.values()) or 1
        score = 0.0
        for term, query_count in query.items():
            tf = terms.get(term, 0)
            if not tf:
                continue
            df = document_frequency[term]
            idf = math.log(1.0 + (len(docs) - df + 0.5) / (df + 0.5))
            score += query_count * idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * length / average_length))
        if score > best_score or (score == best_score and candidate["document_id"] < best_id):
            best_score = score
            best_id = candidate["document_id"]
    return best_id


def main() -> int:
    docs = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    docs.sort(key=lambda item: item["document_id"])
    document_frequency: Counter[str] = Counter()
    for doc in docs:
        document_frequency.update(set(tokens(doc["content"])))

    categories = (["simple"] * 25 + ["paraphrase"] * 20 + ["close_distractor"] * 20 + ["chunk_boundary"] * 15 + ["no_answer"] * 20)
    records = []
    for index, category in enumerate(categories):
        doc = docs[index]
        doc_title = title(doc)
        neighbor = bm25_neighbor(index, docs, document_frequency)
        if category == "simple":
            question = f"What does the Hermes documentation section '{doc_title}' explain?"
            relevant = [doc["document_id"]]
        elif category == "paraphrase":
            question = f"Summarize the operational guidance in '{doc_title}' in different words."
            relevant = [doc["document_id"]]
        elif category == "close_distractor":
            question = f"Which documented details belong specifically to '{doc_title}', rather than to a nearby Hermes topic?"
            relevant = [doc["document_id"]]
        elif category == "chunk_boundary":
            question = f"Which Hermes section connects the introduction and later implementation details for '{doc_title}'?"
            relevant = [doc["document_id"]]
        else:
            question = f"What lunar calibration constant does '{doc_title}' prescribe for an offline telescope controller?"
            relevant = []
        records.append({
            "case_id": f"v1-{index + 1:03d}",
            "category": category,
            "question": question,
            "relevant_document_ids": relevant,
            "distractor_document_ids": [neighbor],
            "distractor_miner": "bm25_stdlib_not_bge_m3",
            "acl_probe": False,
            "manual_review_status": "pending_initial_control" if index < 20 else "pending",
            "decision_reference_status": "pending_human_validation",
        })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "records": len(records), "seed": SEED, "human_validated": 0}, sort_keys=True))
    return 0 if len(records) == 100 else 1


if __name__ == "__main__":
    raise SystemExit(main())
