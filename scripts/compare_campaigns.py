#!/usr/bin/env python3
"""Compare the RAG answer path against the closed-book baseline, offline.

Produces two artefacts from the synthetic track:
  - data/results/campaign-comparison.json : abstention metrics for BOTH campaigns;
  - data/results/campaign-review-sample.jsonl : the >=20% human-review sample,
    each line pairing a question with its RAG answer and closed-book answer plus
    empty verdict fields for a human to fill.

HONESTY / OFFLINE LIMIT: with no LLM endpoint wired in, the RAG side uses the
extractive RagService answer (top authorized chunk text) and the closed-book side
abstains by default (it has nothing to answer from). The abstention axis is real;
answer CORRECTNESS is left to the human review — no offline metric can score it.
When RAG_GENERATOR_* / a real baseline endpoint are provided, swap the injected
answer callables for the networked generators.

Exit codes: 0 on success, 1 on any violation (e.g. stale corpus hash).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import asdict

from rag_hermes.acl import AuthorizationContext
from rag_hermes.campaign_compare import compare_campaigns
from rag_hermes.closed_book import CLOSED_BOOK_ABSTENTION
from rag_hermes.eval_corpus import DEFAULT_CORPUS, corpus_manifest, load_documents
from rag_hermes.evaluation_dataset import is_quality_eligible
from rag_hermes.generator import ABSTENTION_ANSWER as RAG_ABSTENTION
from rag_hermes.synthetic_report import build_public_service

DATASET = ROOT / "data/benchmark/dataset-synthetic.jsonl"
REPORT = ROOT / "data/results/campaign-comparison.json"
REVIEW = ROOT / "data/results/campaign-review-sample.jsonl"


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
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--review", type=Path, default=REVIEW)
    parser.add_argument("--review-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--minimum-score", type=float, default=0.05)
    args = parser.parse_args()

    cases = load_cases(args.dataset)
    documents = load_documents(args.corpus)

    if any(is_quality_eligible(c) for c in cases):
        print("VIOLATION: a quality-eligible case is present in the synthetic track",
              file=sys.stderr)
        return 1

    service = build_public_service(documents, minimum_score=args.minimum_score, top_k=1)
    context = AuthorizationContext(
        tenant_id="public", user_id="evaluator", groups=(), clearance=0
    )

    def rag_answer(question: str) -> str:
        trace = service.answer_with_trace(question, context=context)
        return RAG_ABSTENTION if trace.response.abstained else trace.response.answer

    def closed_book_answer(_question: str) -> str:
        # No baseline endpoint wired in: abstain honestly rather than fabricate.
        return CLOSED_BOOK_ABSTENTION

    try:
        result = compare_campaigns(
            cases,
            rag_answer,
            closed_book_answer,
            review_fraction=args.review_fraction,
            seed=args.seed,
        )
    except ValueError as exc:
        print(f"VIOLATION: {exc}", file=sys.stderr)
        return 1

    report = {
        "track": "synthetic",
        "note": (
            "OFFLINE comparison. RAG = extractive top-chunk answer; closed-book "
            "abstains (no endpoint). Abstention axis is real; answer correctness "
            "is left to the >=20% human review."
        ),
        "total": result.total,
        "review_fraction": args.review_fraction,
        "review_sample_size": len(result.review_sample),
        "rag_abstention_precision": result.rag_abstention_precision,
        "rag_abstention_recall": result.rag_abstention_recall,
        "closed_book_abstention_precision": result.closed_book_abstention_precision,
        "closed_book_abstention_recall": result.closed_book_abstention_recall,
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Human-review file: one pair per line, with empty verdict fields to fill.
    review_lines = []
    for pair in result.review_sample:
        record = asdict(pair)
        record["human_verdict"] = {
            "rag_correct": None,
            "closed_book_correct": None,
            "notes": "",
        }
        review_lines.append(json.dumps(record, ensure_ascii=False))
    args.review.write_text("\n".join(review_lines) + "\n", encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nreview sample -> {args.review} ({len(result.review_sample)} pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
