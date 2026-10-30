#!/usr/bin/env python3
"""Aggregate the human-filled review sample into RAG vs closed-book accuracy.

Reads data/results/campaign-review-sample.jsonl (produced by compare_campaigns.py
and filled in by a human: each human_verdict.rag_correct / closed_book_correct set
to true/false), and writes data/results/campaign-review-aggregate.json.

Answer correctness is the ONLY axis a human can judge and no offline metric can.
Fail-closed by default: if any pair is still unreviewed, the script refuses
(exit 1) rather than publish partial accuracy. Use --allow-partial for an
in-progress snapshot over the reviewed subset only.

Exit codes: 0 on success, 1 on any violation (unreviewed, malformed, empty).
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_hermes.review_aggregate import aggregate_review

REVIEW = ROOT / "data/results/campaign-review-sample.jsonl"
AGGREGATE = ROOT / "data/results/campaign-review-aggregate.json"


def load_pairs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=REVIEW)
    parser.add_argument("--out", type=Path, default=AGGREGATE)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="aggregate over the reviewed subset only (progress snapshot)",
    )
    args = parser.parse_args()

    pairs = load_pairs(args.review)
    if not pairs:
        print(f"empty or missing review file: {args.review}", file=sys.stderr)
        return 1

    try:
        report = aggregate_review(pairs, require_complete=not args.allow_partial)
    except ValueError as exc:
        print(f"VIOLATION: {exc}", file=sys.stderr)
        return 1

    payload = {
        "source": str(args.review),
        "complete_review": not args.allow_partial,
        **asdict(report),
        "note": (
            "Human-judged answer correctness. RAG vs closed-book accuracy is the "
            "only correctness measure; abstention and recall are reported "
            "elsewhere. Denominator is the reviewed count."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
