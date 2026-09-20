#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import json

from rag_hermes.benchmark import run_lexical_benchmark
from rag_hermes.dataset import load_documents, load_questions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", action="append", required=True)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--minimum-score", type=float, default=0.5)
    args = parser.parse_args()

    documents = []
    for path in args.documents:
        documents.extend(load_documents(path))
    questions = load_questions(args.questions)
    report, cases = run_lexical_benchmark(
        documents, questions, k=args.k, minimum_score=args.minimum_score
    )
    print(json.dumps({
        "report": asdict(report),
        "cases": [asdict(case) for case in cases],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
