#!/usr/bin/env python3
"""Ablation CPU du chunking : ancien (mots) vs nouveau (tokens-borne).

Mesure sur le VRAI corpus, sans GPU, la partie causale accessible localement :
combien de paires question+passage depasseraient la fenetre 512 du reranker
selon la strategie de chunking.

Limite assumee : le comptage de tokens est une ESTIMATION via un ratio
mots->tokens explicite (teste sur plusieurs valeurs). Le comptage exact du
tokenizer bge-reranker-v2-m3 (rejets 190 exacts, Recall 0,667->1,0) reste un
point GPU separe. Ce script prouve le MECANISME, pas le chiffre exact.
"""
from __future__ import annotations

import json
from pathlib import Path

from rag_hermes.chunking_ablation import count_pairs_over_budget
from rag_hermes.dataset import load_documents
from rag_hermes.ingestion import chunk_document

ROOT = Path(__file__).resolve().parents[1]
CORPUS = [
    ROOT / "data/generated/hermes_public_documents.jsonl",
    ROOT / "data/fixtures/private_and_synthetic_documents.jsonl",
]
OUTPUT = ROOT / "data/results/chunking_ablation_cpu.json"
RERANKER_MAX_LENGTH = 512
QUESTION_WORDS = 8  # borne haute des questions du smoke (max observe 7)
SPECIAL_TOKENS = 4
RATIOS = [1.2, 1.3, 1.4, 1.5]

# Bornes token du chunking neuf : 384 tokens -> ~274 mots a 1.4
OLD_MAX_WORDS = 420
OLD_OVERLAP = 40
NEW_MAX_PASSAGE_TOKENS = 384


def main() -> None:
    documents = []
    for path in CORPUS:
        documents.extend(load_documents(path))

    # Ancien chunking : par mots (420/40), comme le run 2 945 chunks
    old_chunks = [
        chunk
        for document in documents
        for chunk in chunk_document(
            document, max_tokens=OLD_MAX_WORDS, overlap_tokens=OLD_OVERLAP
        )
    ]
    old_word_counts = [len(chunk.text.split()) for chunk in old_chunks]

    report = {
        "classification": "cpu_mechanism_only_not_exact_token_count",
        "reranker_max_length": RERANKER_MAX_LENGTH,
        "question_words_assumed": QUESTION_WORDS,
        "special_tokens_assumed": SPECIAL_TOKENS,
        "corpus_documents": len(documents),
        "old_strategy": {
            "name": "word_chunking_420_40",
            "chunk_count": len(old_chunks),
            "max_chunk_words": max(old_word_counts),
            "median_chunk_words": sorted(old_word_counts)[len(old_word_counts) // 2],
        },
        "new_strategy": {
            "name": "token_chunking_384_64",
            "max_passage_tokens": NEW_MAX_PASSAGE_TOKENS,
            "note": (
                "borne par construction : chaque passage <= 384 tokens, donc "
                "paire <= 384 + question + special, structurellement < 512"
            ),
        },
        "over_budget_by_ratio": {},
        "caveat_vs_gpu_run": (
            "Le run GPU historique montrait 190/200 rejets, pas ~85%, car le "
            "reranker ne voyait que les 20 candidats retrouves par question, pas "
            "tout le corpus. Cette ablation mesure la fraction de chunks trop "
            "longs dans le corpus entier ; les deux convergent sur le mecanisme "
            "(chunks par mots trop longs -> rejet), pas sur le chiffre exact."
        ),
    }

    for ratio in RATIOS:
        old_over = count_pairs_over_budget(
            old_word_counts,
            QUESTION_WORDS,
            max_length=RERANKER_MAX_LENGTH,
            words_to_tokens=ratio,
            special_tokens=SPECIAL_TOKENS,
        )
        # Nouveau : passage borne a 384 tokens -> mots equivalents = 384/ratio
        new_equiv_words = int(NEW_MAX_PASSAGE_TOKENS / ratio)
        new_over = count_pairs_over_budget(
            [new_equiv_words],
            QUESTION_WORDS,
            max_length=RERANKER_MAX_LENGTH,
            words_to_tokens=ratio,
            special_tokens=SPECIAL_TOKENS,
        )
        report["over_budget_by_ratio"][str(ratio)] = {
            "old_word_chunks_over_512": old_over,
            "old_fraction_over": round(old_over / len(old_chunks), 4),
            "new_token_chunk_over_512": new_over,
        }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
