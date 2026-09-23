#!/usr/bin/env python3
"""Validate the whole v2 evaluation dataset and report human-review readiness.

Exit codes:
  0  all target invariants satisfied AND human review complete on the 100 refs;
  2  structurally valid but review/volume targets not yet met (expected, honest gate);
  1  a structural / anti-circularity violation was found.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_hermes.eval_corpus import corpus_manifest, load_documents
from rag_hermes.evaluation_dataset import validate_evaluation_case

DATASET = ROOT / "data/benchmark/dataset-v2.jsonl"

TARGET_EN = 100
TARGET_FR_PAIRS = 40
REVIEW_STATUSES_DONE = {"validated", "arbitrated"}


def load_cases() -> list[dict]:
    if not DATASET.exists():
        return []
    return [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]


def span_signature(case: dict) -> tuple:
    return tuple(sorted(
        (s["document_id"], s["start_char"], s["end_char"], s["passage_sha256"], s["relevance_grade"])
        for s in case["relevance_spans"]
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete", action="store_true",
                        help="exit 2 unless volume + full human review targets are met")
    args = parser.parse_args()

    cases = load_cases()
    if not cases:
        print(json.dumps({"status": "empty", "dataset": str(DATASET)}))
        return 2

    documents = load_documents()
    manifest = corpus_manifest()

    # 1. Structural + anti-circularity validation of every case.
    ids: set[str] = set()
    for case in cases:
        if case["case_id"] in ids:
            print(f"VIOLATION: duplicate case_id {case['case_id']}", file=sys.stderr)
            return 1
        ids.add(case["case_id"])
        try:
            validate_evaluation_case(case, documents, manifest)
        except ValueError as exc:
            print(f"VIOLATION in {case['case_id']}: {exc}", file=sys.stderr)
            return 1

    # 2. Pair integrity: same pair_id => one EN + one FR, identical spans.
    pairs: dict[str, list[dict]] = {}
    for case in cases:
        if "pair_id" in case:
            pairs.setdefault(case["pair_id"], []).append(case)
    complete_pairs = 0
    for pair_id, members in pairs.items():
        langs = sorted(m["language"] for m in members)
        if langs == ["en", "fr"]:
            if span_signature(members[0]) != span_signature(members[1]):
                print(f"VIOLATION: pair {pair_id} EN/FR spans differ", file=sys.stderr)
                return 1
            complete_pairs += 1
        elif len(members) > 1:
            print(f"VIOLATION: pair {pair_id} is not exactly one EN + one FR: {langs}",
                  file=sys.stderr)
            return 1

    en = [c for c in cases if c["track"] == "en2en"]
    fr = [c for c in cases if c["track"] == "fr2en"]
    reviewed = sum(1 for c in cases if c["reference_status"] in REVIEW_STATUSES_DONE)

    report = {
        "total": len(cases),
        "en2en": len(en),
        "fr2en": len(fr),
        "complete_en_fr_pairs": complete_pairs,
        "reviewed": reviewed,
        "pending": len(cases) - reviewed,
        "target_en": TARGET_EN,
        "target_fr_pairs": TARGET_FR_PAIRS,
        "structural": "valid",
    }

    targets_met = (len(en) >= TARGET_EN and complete_pairs >= TARGET_FR_PAIRS
                   and reviewed == len(cases))
    report["status"] = "READY" if targets_met else "BLOCKED_review_or_volume"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if targets_met else 2


if __name__ == "__main__":
    raise SystemExit(main())
