#!/usr/bin/env python3
"""Consolidate synthetic retrieval, abstention and human-review reports.

Exit codes:
  0  synthetic technical campaign complete (including the human sample)
  2  structurally valid but blocked by missing/incomplete human review
  1  invalid/inconsistent inputs or failed security gate

Even a complete synthetic campaign is NEVER quality evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_hermes.campaign_summary import build_campaign_summary

RETRIEVAL = ROOT / "data/results/synthetic-eval-report.json"
COMPARISON = ROOT / "data/results/campaign-comparison.json"
HUMAN = ROOT / "data/results/campaign-review-aggregate.json"
OUTPUT = ROOT / "data/results/campaign-summary.json"


def _load_required(path: Path, label: str) -> dict:
    if not path.exists():
        raise ValueError(f"missing {label} report: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} report must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval", type=Path, default=RETRIEVAL)
    parser.add_argument("--comparison", type=Path, default=COMPARISON)
    parser.add_argument("--human", type=Path, default=HUMAN)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()

    try:
        retrieval = _load_required(args.retrieval, "retrieval")
        comparison = _load_required(args.comparison, "comparison")
        human = (
            _load_required(args.human, "human review")
            if args.human.exists()
            else None
        )
        report = build_campaign_summary(retrieval, comparison, human)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"VIOLATION: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if report["status"] == "COMPLETE_synthetic_technical_witness":
        return 0
    if report["status"].startswith("BLOCKED_"):
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
