#!/usr/bin/env python3
"""Migrate the legacy v1 benchmark into a separate SYNTHETIC evaluation track.

Reads data/benchmark/dataset-v1.jsonl (machine-generated questions, document-
level labels) and writes data/benchmark/dataset-synthetic.jsonl, where every
case:
  - is validated against the canonical strict schema;
  - is honestly marked question_provenance = synthetic_generated_from_corpus
    (is_quality_eligible == False), so it can never inflate a human-grade score;
  - uses FULL-DOCUMENT relevance spans (document-granularity recall, not passage).

This track is intentionally kept OUT of dataset-v2.jsonl (the human track). The
v2 readiness gate is unaffected. Exit codes: 0 on success, 1 on any violation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_hermes.eval_corpus import DEFAULT_CORPUS, corpus_manifest, load_documents
from rag_hermes.evaluation_dataset import is_quality_eligible
from rag_hermes.synthetic_dataset import build_synthetic_case

SOURCE = ROOT / "data/benchmark/dataset-v1.jsonl"
TARGET = ROOT / "data/benchmark/dataset-synthetic.jsonl"


def load_rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--target", type=Path, default=TARGET)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args()

    rows = load_rows(args.source)
    documents = load_documents(args.corpus)
    manifest = corpus_manifest(args.corpus)

    cases: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        case_id = str(row.get("case_id"))
        if case_id in seen:
            print(f"VIOLATION: duplicate case_id {case_id}", file=sys.stderr)
            return 1
        seen.add(case_id)
        try:
            cases.append(build_synthetic_case(row, documents, manifest))
        except (ValueError, KeyError) as exc:
            print(f"VIOLATION in {case_id}: {exc}", file=sys.stderr)
            return 1

    # Non-circularity invariant: not a single case may be quality-eligible.
    if any(is_quality_eligible(case) for case in cases):
        print("VIOLATION: a synthetic case was marked quality-eligible", file=sys.stderr)
        return 1

    args.target.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases
    )
    args.target.write_text(payload, encoding="utf-8")

    answerable = sum(1 for c in cases if not c["should_abstain"])
    abstention = sum(1 for c in cases if c["should_abstain"])
    report = {
        "track": "synthetic",
        "total": len(cases),
        "answerable_full_document_spans": answerable,
        "abstention": abstention,
        "quality_eligible": sum(1 for c in cases if is_quality_eligible(c)),
        "reference_status_pending": sum(
            1 for c in cases if c["reference_status"] == "pending"
        ),
        "target": str(args.target),
        "note": "document-granularity spans; provenance synthetic; NOT human quality evidence",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
