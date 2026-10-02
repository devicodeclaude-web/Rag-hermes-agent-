#!/usr/bin/env python3
"""Pre-check a human-filled evaluation batch WITHOUT writing anything.

Where ``ingest_manual_batch`` stops at the first violation (and is atomic), this
dry-run validator reports EVERY problem it can find in one pass, so the annotator
can fix a whole draft before the real ingest. It never touches the dataset.

For each row it reports: the 0-based ``index``, the ``case_id`` (if any), and a
human-readable ``message``. Problems detected:
  - invalid JSON on a line (reported with the raw line number);
  - unresolved ``REMPLIR`` placeholder tokens left in any field;
  - ``case_id`` missing, duplicated within the batch, or already in the dataset;
  - any schema / anti-circularity / corpus violation raised by ``build_case``
    (wrong track/language, unknown document_id, passage not found or ambiguous,
    abstention/passage inconsistencies, etc.).

Exit codes: 0 = no problems (ready to ingest); 2 = one or more problems found;
1 = the batch file itself could not be read.
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
from scripts.annotate_eval_case import build_case

DATASET = ROOT / "data/benchmark/dataset-v2.jsonl"
PLACEHOLDER_TOKEN = "REMPLIR"


def _existing_ids() -> set[str]:
    if not DATASET.exists():
        return set()
    return {
        json.loads(line)["case_id"]
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _has_placeholder(value) -> bool:
    """True if any string anywhere in ``value`` still contains REMPLIR."""
    if isinstance(value, str):
        return PLACEHOLDER_TOKEN in value
    if isinstance(value, dict):
        return any(_has_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_placeholder(v) for v in value)
    return False


def check_batch(raw_rows, documents, manifest, existing_ids) -> list[dict]:
    """Return a list of problems for a batch. Never writes anything.

    Each problem is ``{"index": int, "case_id": str|None, "message": str}``.
    All rows are inspected; the list is empty iff the batch is ready to ingest.
    """
    problems: list[dict] = []
    seen_in_batch: set[str] = set()

    for index, raw in enumerate(raw_rows):
        case_id = raw.get("case_id") if isinstance(raw, dict) else None

        def add(message: str) -> None:
            problems.append({"index": index, "case_id": case_id, "message": message})

        if not isinstance(raw, dict):
            add("row is not a JSON object")
            continue

        # 1. Unresolved template placeholders.
        if _has_placeholder(raw):
            add(f"unresolved {PLACEHOLDER_TOKEN} placeholder still present; fill it in")

        # 2. case_id presence / duplication / prior existence.
        if not case_id:
            add("missing case_id")
        else:
            if case_id in existing_ids:
                add(f"case_id already in dataset: {case_id}")
            if case_id in seen_in_batch:
                add(f"duplicate case_id within this batch: {case_id}")
            seen_in_batch.add(case_id)

        # 3. Full canonical validation (schema + anti-circularity + corpus).
        #    build_case raises on the first violation it finds in this row.
        try:
            build_case(raw, documents, manifest)
        except (ValueError, KeyError, TypeError) as exc:
            add(str(exc))

    return problems


def run(batch_path: Path) -> int:
    try:
        text = batch_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read batch file: {exc}", file=sys.stderr)
        return 1

    raw_rows: list = []
    json_errors: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw_rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            json_errors.append({"index": lineno - 1, "case_id": None,
                                "message": f"invalid JSON on line {lineno}: {exc}"})

    documents = load_documents(DEFAULT_CORPUS)
    manifest = corpus_manifest(DEFAULT_CORPUS)
    existing = _existing_ids()

    problems = json_errors + check_batch(raw_rows, documents, manifest, existing)

    # Align acceptance semantics with ingest_manual_batch, which refuses an empty
    # batch (exit 1). A batch with no parsable rows is never "ready to ingest".
    if not raw_rows and not json_errors:
        problems.append({"index": None, "case_id": None,
                         "message": "empty batch: nothing to ingest"})

    summary = {
        "batch": str(batch_path),
        "rows_parsed": len(raw_rows),
        "problem_count": len(problems),
        "status": "READY_TO_INGEST" if not problems else "HAS_PROBLEMS",
        "problems": problems,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not problems else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path, help="JSONL file, one raw case per line")
    args = parser.parse_args()
    return run(args.batch)


if __name__ == "__main__":
    raise SystemExit(main())
