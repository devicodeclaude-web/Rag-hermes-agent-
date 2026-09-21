"""Ablation CPU du chunking : partie causale mesurable sans GPU.

Cette ablation isole la cause structurelle de rejets 190->0 observee entre
l'ancien run (2 945 chunks, chunking par mots 420/40) et le nouveau
(7 371 chunks, chunking par tokens 384/64).

Elle NE pretend PAS reproduire le comptage exact du tokenizer bge-reranker.
Elle mesure une borne : le nombre de mots par chunk, converti en tokens via un
ratio calibre et EXPLICITE, puis combine a une question courte pour verifier le
depassement de la fenetre 512 du reranker.

Le comptage exact (rejets 190, Recall 0,667->1,0) reste un point GPU separe.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AblationResult:
    strategy: str
    chunk_count: int
    max_chunk_units: int
    pairs_over_budget: int
    total_pairs: int


def estimate_pair_tokens(
    chunk_word_count: int,
    question_word_count: int,
    *,
    words_to_tokens: float,
    special_tokens: int,
) -> float:
    """Borne haute approximative des tokens d'une paire question+passage.

    words_to_tokens est un ratio EXPLICITE (mots -> tokens BPE). Pour le francais
    technique, 1,3-1,5 est realiste ; on l'expose comme parametre pour ne rien
    cacher plutot que de le coder en dur.
    """
    if words_to_tokens <= 0:
        raise ValueError("words_to_tokens must be positive")
    if special_tokens < 0:
        raise ValueError("special_tokens must be non-negative")
    return (chunk_word_count + question_word_count) * words_to_tokens + special_tokens


def count_pairs_over_budget(
    chunk_word_counts: list[int],
    question_word_count: int,
    *,
    max_length: int,
    words_to_tokens: float,
    special_tokens: int,
) -> int:
    over = 0
    for words in chunk_word_counts:
        estimated = estimate_pair_tokens(
            words,
            question_word_count,
            words_to_tokens=words_to_tokens,
            special_tokens=special_tokens,
        )
        if estimated > max_length:
            over += 1
    return over
