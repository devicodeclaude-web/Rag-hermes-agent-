#!/usr/bin/env python3
"""Vérifie que le corpus d'éval versionné correspond au lock épinglé.

Compare l'identité du corpus (`source_revision` + `corpus_manifest_sha`, calculée
par `rag_hermes.eval_corpus.corpus_manifest`) aux valeurs figées dans
`manifests/locks/corpus.lock.json`. Épingle à la fois la VERSION (révision source
unique extraite des `source_uri`) et le HASH (sha256 du fichier canonique).

Usage :
    PYTHONPATH=. python3 scripts/verify_corpus_lock.py

Sort 1 si le fichier manque ou si version/hash divergent du lock.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rag_hermes.eval_corpus import DEFAULT_CORPUS, corpus_manifest

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "manifests/locks/corpus.lock.json"


def main() -> int:
    if not DEFAULT_CORPUS.exists():
        print(f"ÉCHEC: corpus absent: {DEFAULT_CORPUS}")
        return 1
    if not LOCK.exists():
        print(f"ÉCHEC: lock absent: {LOCK}")
        return 1
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    actual = corpus_manifest()
    problems = []
    for key in ("source_revision", "corpus_manifest_sha"):
        if lock.get(key) != actual.get(key):
            problems.append(f"{key}: lock={lock.get(key)!r} réel={actual.get(key)!r}")
    print(f"corpus={DEFAULT_CORPUS.name}")
    print(f"source_revision={actual['source_revision']}")
    print(f"corpus_manifest_sha={actual['corpus_manifest_sha']}")
    if problems:
        print("\nÉCHEC VÉRIFICATION LOCK:")
        for p in problems:
            print("  -", p)
        return 1
    print("\nLOCK OK (version + hash conformes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
