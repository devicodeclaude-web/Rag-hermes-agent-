#!/usr/bin/env python3
"""Ingest a human-filled batch of evaluation questions into the v2 dataset.

Workflow for the human annotator:
  1. Write questions WITHOUT reading the corpus (anti-circularity).
  2. For each answerable question, locate the passage that answers it and copy
     it verbatim into "passage_text"; offsets + SHA-256 are computed here.
  3. Fill one JSON object per line in a batch file (see templates/manual_eval_batch.template.jsonl).
  4. Run this script; it validates the WHOLE batch first and only writes if every
     row is valid (atomic: an invalid row writes nothing).

Each row is the same "raw" shape consumed by scripts/annotate_eval_case.build_case:

  {
    "case_id": "m-001-en", "pair_id": "m-001",
    "question": "...", "language": "en", "track": "en2en",
    "category": "simple", "access_scope": "public",
    "question_provenance": "human_task_without_corpus_view",
    "should_abstain": false, "unanswerable_reason": null,
    "reference_status": "pending",
    "relevant_passages": [
      {"document_id": "hermes-agent:...md", "passage_text": "…verbatim…", "relevance_grade": 2}
    ]
  }

Exit codes: 0 = whole batch ingested; 1 = a violation was found (nothing written).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_hermes.eval_corpus import DEFAULT_CORPUS, corpus_manifest, load_documents
from scripts.annotate_eval_case import build_case

DATASET = ROOT / "data/benchmark/dataset-v2.jsonl"
CORPUS = DEFAULT_CORPUS


def _existing_ids() -> set[str]:
    if not DATASET.exists():
        return set()
    return {
        json.loads(line)["case_id"]
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _atomic_append_all(cases: list[dict]) -> None:
    DATASET.parent.mkdir(parents=True, exist_ok=True)
    old = DATASET.read_text(encoding="utf-8") if DATASET.exists() else ""
    additions = "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases
    )
    fd, tmp = tempfile.mkstemp(dir=str(DATASET.parent), suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            handle.write(old + additions)
        Path(tmp).replace(DATASET)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def run(batch_path: Path) -> int:
    documents = load_documents(CORPUS)
    manifest = corpus_manifest(CORPUS)

    raw_rows = [
        json.loads(line)
        for line in batch_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not raw_rows:
        print("empty batch: nothing to ingest", file=sys.stderr)
        return 1

    existing = _existing_ids()
    seen_in_batch: set[str] = set()
    built: list[dict] = []
    # Validate the WHOLE batch before writing a single line (atomic ingest).
    for index, raw in enumerate(raw_rows):
        case_id = raw.get("case_id")
        if not case_id:
            print(f"VIOLATION row {index}: missing case_id", file=sys.stderr)
            return 1
        if case_id in existing:
            print(f"VIOLATION row {index}: case_id already in dataset: {case_id}", file=sys.stderr)
            return 1
        if case_id in seen_in_batch:
            print(f"VIOLATION row {index}: duplicate case_id in batch: {case_id}", file=sys.stderr)
            return 1
        seen_in_batch.add(case_id)
        try:
            built.append(build_case(raw, documents, manifest))
        except (ValueError, KeyError) as exc:
            print(f"VIOLATION row {index} ({case_id}): {exc}", file=sys.stderr)
            return 1

    _atomic_append_all(built)
    print(json.dumps({
        "ingested": len(built),
        "dataset": str(DATASET),
        "case_ids": [c["case_id"] for c in built],
    }, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path, help="JSONL file, one raw case per line")
    args = parser.parse_args()
    return run(args.batch)


if __name__ == "__main__":
    raise SystemExit(main())
