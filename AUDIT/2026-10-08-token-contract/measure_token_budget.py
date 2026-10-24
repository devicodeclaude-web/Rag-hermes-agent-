#!/usr/bin/env python3
"""Preuve CPU du contrat de tokens (Lot 2) — exécuté 2026-10-08, sans GPU.

Rejoue le comptage EXACT des paires question+passage avec le tokenizer réel du
reranker (BAAI/bge-reranker-v2-m3 @ révision verrouillée), pour les deux
stratégies de découpage :
  - ANCIENNE : chunk_document (mots, 420/40)
  - NOUVELLE : chunk_document_tokens (tokens exacts, 384/64)

Mesure : nombre de chunks, longueurs de paires (min/p50/p95/max) et paires
hors budget (>512). Aucun GPU : seule la tokenisation (CPU) est utilisée.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from transformers import AutoTokenizer

from rag_hermes.dataset import load_documents, load_questions
from rag_hermes.ingestion import chunk_document, chunk_document_tokens
from rag_hermes.reranker_budget import count_pair_tokens, passage_token_budget

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TOKENIZER_DIR = "/root/work/models/bge-reranker-v2-m3"
TOKENIZER_NAME = "BAAI/bge-reranker-v2-m3"
TOKENIZER_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
MAX_LENGTH = 512


def pctl(values, p):
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return s[k]


def dist(values):
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "p50": pctl(values, 50),
        "p95": pctl(values, 95),
        "max": max(values) if values else None,
    }


def main() -> None:
    tok = AutoTokenizer.from_pretrained(TOKENIZER_DIR, local_files_only=True)

    documents = load_documents(ROOT / "data/generated/hermes_public_documents.jsonl")
    documents += load_documents(ROOT / "data/fixtures/private_and_synthetic_documents.jsonl")
    questions = load_questions(ROOT / "data/fixtures/smoke_questions.jsonl")

    # Invariant de tokens spéciaux : len(pair) == len(q) + len(p) + special.
    sample_special = set()
    for q in questions[:3]:
        for d in documents[:3]:
            p = d.content[:200]
            lq = len(tok(q.question, add_special_tokens=False)["input_ids"])
            lp = len(tok(p, add_special_tokens=False)["input_ids"])
            sample_special.add(count_pair_tokens(tok, q.question, p) - lq - lp)
    assert sample_special == {4}, f"special-token invariant broke: {sample_special}"

    old_chunks = [c for d in documents for c in chunk_document(d, max_tokens=420, overlap_tokens=40)]
    new_chunks = [
        c
        for d in documents
        for c in chunk_document_tokens(
            d, tok, max_passage_tokens=384, overlap_tokens=64,
            tokenizer_name=TOKENIZER_NAME, tokenizer_revision=TOKENIZER_REVISION,
        )
    ]

    # Budget de passage dérivé de la marge de question NOMMÉE (manifeste 96/32).
    derived_passage_budget = passage_token_budget(
        reranker_max_length=MAX_LENGTH, question_token_margin=96, special_token_reserve=32
    )

    # Longueur exacte de chaque paire question x chunk (borne supérieure de ce
    # que le reranker pourrait voir ; même convention que l'ablation committée).
    def pair_lengths(chunks):
        q_ids = {q.case_id: len(tok(q.question, add_special_tokens=False)["input_ids"]) for q in questions}
        lengths = []
        over = 0
        for c in chunks:
            lp = len(tok(c.text, add_special_tokens=False)["input_ids"])
            for q in questions:
                total = q_ids[q.case_id] + lp + 4  # +4 tokens spéciaux XLM-R (vérifié)
                lengths.append(total)
                if total > MAX_LENGTH:
                    over += 1
        return lengths, over

    def passage_lengths(chunks):
        return [len(tok(c.text, add_special_tokens=False)["input_ids"]) for c in chunks]

    old_pairs, old_over = pair_lengths(old_chunks)
    new_pairs, new_over = pair_lengths(new_chunks)
    old_pass = passage_lengths(old_chunks)
    new_pass = passage_lengths(new_chunks)

    report = {
        "executed_utc": "2026-10-08",
        "classification": "exact_token_count_cpu_only_no_gpu",
        "tokenizer": {"name": TOKENIZER_NAME, "revision": TOKENIZER_REVISION, "special_tokens_per_pair": 4},
        "corpus": {"documents": len(documents), "questions": len(questions)},
        "reranker_max_length": MAX_LENGTH,
        "derived_passage_budget_from_named_question_margin": derived_passage_budget,
        "before_word_chunking_420_40": {
            "chunks": len(old_chunks),
            "passage_tokens": dist(old_pass),
            "pair_tokens": dist(old_pairs),
            "pairs_over_budget": old_over,
            "pairs_total": len(old_pairs),
            "fraction_over": round(old_over / len(old_pairs), 4) if old_pairs else None,
        },
        "after_token_chunking_384_64": {
            "chunks": len(new_chunks),
            "passage_tokens": dist(new_pass),
            "pair_tokens": dist(new_pairs),
            "pairs_over_budget": new_over,
            "pairs_total": len(new_pairs),
            "fraction_over": round(new_over / len(new_pairs), 4) if new_pairs else None,
        },
    }
    (OUT / "token_budget_measurement.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
