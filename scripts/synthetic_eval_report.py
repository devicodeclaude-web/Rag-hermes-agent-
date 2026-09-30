#!/usr/bin/env python3
"""Produce a document-granularity retrieval report for the SYNTHETIC track.

Runs data/benchmark/dataset-synthetic.jsonl through the real RagService answer
path over the full public corpus, and writes a JSON report to data/results/.

HONESTY: the synthetic questions are corpus-generated and labelled at whole-
document granularity, so this report is a TECHNICAL WITNESS of lexical document
retrieval — NOT human-grade quality evidence. The default retriever is the
in-memory lexical baseline (no embeddings, no reranker), which is exactly why
numbers here are a floor, not a quality claim.

Exit codes: 0 on success, 1 on any violation (e.g. stale corpus hash).
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_hermes.eval_corpus import DEFAULT_CORPUS, corpus_manifest, load_documents
from rag_hermes.evaluation_dataset import is_quality_eligible
from rag_hermes.synthetic_report import run_synthetic_evaluation

DATASET = ROOT / "data/benchmark/dataset-synthetic.jsonl"
RESULTS = ROOT / "data/results/synthetic-eval-report.json"


def load_cases(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--minimum-score", type=float, default=0.05)
    args = parser.parse_args()

    cases = load_cases(args.dataset)
    documents = load_documents(args.corpus)
    manifest = corpus_manifest(args.corpus)

    # Guard: this report exists precisely because these cases are NOT quality
    # evidence. If any case were quality-eligible, refuse — the synthetic report
    # must never be mistaken for a human-grade measurement.
    if any(is_quality_eligible(c) for c in cases):
        print("VIOLATION: a quality-eligible case is present in the synthetic track",
              file=sys.stderr)
        return 1

    started = time.time()
    try:
        report = run_synthetic_evaluation(
            cases=cases,
            documents=documents,
            manifest=manifest,
            k=args.k,
            minimum_score=args.minimum_score,
        )
    except (ValueError, KeyError) as exc:
        print(f"VIOLATION: {exc}", file=sys.stderr)
        return 1
    elapsed = time.time() - started

    answerable = sum(1 for c in cases if not c["should_abstain"])
    abstention = sum(1 for c in cases if c["should_abstain"])
    payload = {
        "track": "synthetic",
        "provenance": "synthetic_generated_from_corpus",
        "quality_eligible": False,
        "granularity": "document",
        "retriever": "in_memory_lexical_baseline",
        "k": args.k,
        "minimum_score": args.minimum_score,
        "corpus_documents": len(documents),
        "cases_total": len(cases),
        "cases_answerable": answerable,
        "cases_abstention": abstention,
        "source_revision": manifest["source_revision"],
        "corpus_manifest_sha": manifest["corpus_manifest_sha"],
        "elapsed_seconds": round(elapsed, 2),
        "metrics": asdict(report),
        "note": (
            "TECHNICAL WITNESS ONLY. Corpus-generated questions, whole-document "
            "relevance, lexical baseline retriever. Not human-grade quality evidence."
        ),
    }

    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
