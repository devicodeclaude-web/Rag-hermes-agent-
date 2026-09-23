#!/usr/bin/env python3
"""Append a single evaluation case to the v2 dataset, without ever showing the corpus.

Anti-circularity contract:
  - The question is authored WITHOUT viewing the corpus (provenance is recorded).
  - The annotator provides the relevant passage TEXT (verbatim); offsets and the
    SHA-256 are computed here, so labels stay chunking-independent.
  - Every case is validated by rag_hermes.evaluation_dataset before being written.
  - EN and FR versions of the same question share a pair_id (label annotated once).

The case payload is read from a JSON file or stdin, e.g.:

  {
    "case_id": "q-001-en",
    "pair_id": "q-001",
    "question": "How do I add a new platform adapter?",
    "language": "en",
    "track": "en2en",
    "category": "simple",
    "access_scope": "public",
    "question_provenance": "human_task_without_corpus_view",
    "should_abstain": false,
    "unanswerable_reason": null,
    "reference_status": "pending",
    "relevant_passages": [
      {"document_id": "hermes-agent:developer-guide/adding-platform-adapters.md",
       "passage_text": "…verbatim text copied from the document…",
       "relevance_grade": 2}
    ]
  }

For an abstention case, set "should_abstain": true, "relevant_passages": [] and a
non-empty "unanswerable_reason".
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

from rag_hermes.eval_corpus import corpus_manifest, find_passage_span, load_documents
from rag_hermes.evaluation_dataset import validate_evaluation_case

DATASET = ROOT / "data/benchmark/dataset-v2.jsonl"


def build_case(raw: dict, documents, manifest) -> dict:
    spans = []
    for passage in raw.get("relevant_passages", []):
        span = find_passage_span(documents, passage["document_id"], passage["passage_text"])
        span["relevance_grade"] = passage["relevance_grade"]
        spans.append(span)

    case = {
        "case_id": raw["case_id"],
        "question": raw["question"],
        "language": raw["language"],
        "track": raw["track"],
        "category": raw["category"],
        "access_scope": raw["access_scope"],
        "question_provenance": raw["question_provenance"],
        "should_abstain": raw["should_abstain"],
        "unanswerable_reason": raw.get("unanswerable_reason"),
        "reference_status": raw.get("reference_status", "pending"),
        "source_revision": manifest["source_revision"],
        "corpus_manifest_sha": manifest["corpus_manifest_sha"],
        "relevance_spans": spans,
    }
    if "pair_id" in raw:
        case["pair_id"] = raw["pair_id"]
    # Full schema validation (raises on any violation).
    validate_evaluation_case(case, documents, manifest)
    return case


def existing_case_ids() -> set[str]:
    if not DATASET.exists():
        return set()
    ids = set()
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        if line.strip():
            ids.add(json.loads(line)["case_id"])
    return ids


def atomic_append(case: dict) -> None:
    DATASET.parent.mkdir(parents=True, exist_ok=True)
    old = DATASET.read_text(encoding="utf-8") if DATASET.exists() else ""
    new = old + json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(DATASET.parent), suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            handle.write(new)
        Path(tmp).replace(DATASET)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, help="JSON file with the case (default: stdin)")
    args = parser.parse_args()

    raw_text = args.case.read_text(encoding="utf-8") if args.case else sys.stdin.read()
    raw = json.loads(raw_text)

    documents = load_documents()
    manifest = corpus_manifest()

    if raw["case_id"] in existing_case_ids():
        print(f"refused: case_id already present: {raw['case_id']}", file=sys.stderr)
        return 2

    case = build_case(raw, documents, manifest)
    atomic_append(case)
    print(json.dumps({"appended": case["case_id"], "track": case["track"],
                      "spans": len(case["relevance_spans"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
