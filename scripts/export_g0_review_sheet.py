#!/usr/bin/env python3
"""Derive a BLIND human-review sheet from the G0 closed-book execution receipt.

The mandatory >=20% blind review of docs/evaluation-protocol-v2.md judges the
correctness of the concrete answers the model produced (no offline metric can).
For the review to be *blind*, the reviewer must NOT see the gold ``should_abstain``
label nor the ``case_id`` (which is cross-referenceable to the gold dataset),
otherwise the expected answer leaks and the judgement is biased.

This tool reads the verified receipt (``load_consumable_receipt_v2``), keeps only
the concrete answers (``did_abstain is False``), and writes TWO artifacts:

  - a BLIND sheet (``review_id, question, model_answer`` + empty verdict/notes),
    shuffled by a fixed seed so position carries no signal and the order is
    reproducible;
  - a de-blinding KEY (``review_id -> case_id`` + source provenance), kept in a
    SEPARATE file so the sheet alone carries no gold label.

The receipt stays the single hash-protected source of truth; these are derived,
non-authoritative review aids.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path

from rag_hermes.execution_receipt import load_consumable_receipt_v2

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / "data/results/g0_closed_book_human_154_execution_receipt.json"
DEFAULT_SHEET = ROOT / "data/review/g0-closed-book-blind-review-sheet.csv"
DEFAULT_KEY = ROOT / "data/review/g0-closed-book-blind-review-key.json"
# Fixed seed: the shuffle must be reproducible run-to-run and reviewer-to-reviewer.
DEFAULT_SEED = "g0-closed-book-human-154-blind"


def _concrete_answers(report: dict) -> list[dict]:
    """The concrete (non-abstention) answers — the review target.

    ``answer_records`` holds every non-failing case with its gold label; a blind
    review only looks at the answers the model actually committed to.
    """
    records = report.get("answer_records")
    if not isinstance(records, list):
        raise ValueError(
            "receipt report has no answer_records: it predates answer capture; "
            "re-run G0 on the pinned revision that embeds verbatim answers."
        )
    answered = [r for r in records if r.get("did_abstain") is False]
    if not answered:
        raise ValueError("no concrete answers to review (model abstained on all cases)")
    return answered


def build_blind_rows(
    answered: list[dict], seed: str
) -> tuple[list[dict], dict[str, str]]:
    """Return (blind rows, review_id->case_id key), shuffled deterministically.

    Pure function (no IO): review_id is a stable 'rNNN' assigned AFTER shuffling,
    so neither the id nor the row order leaks the dataset order.
    """
    shuffled = list(answered)
    random.Random(seed).shuffle(shuffled)
    width = max(3, len(str(len(shuffled))))
    rows: list[dict] = []
    key: dict[str, str] = {}
    for index, record in enumerate(shuffled, start=1):
        review_id = f"r{index:0{width}d}"
        rows.append(
            {
                "review_id": review_id,
                "question": record["question"],
                "model_answer": record["answer"],
                "correct": "",  # reviewer fills: yes/partial/no
                "grounded": "",  # reviewer fills: yes/no (any unsupported claim?)
                "notes": "",
            }
        )
        key[review_id] = record["case_id"]
    return rows, key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    args = parser.parse_args()

    receipt = load_consumable_receipt_v2(Path(args.receipt))
    report = receipt["report"]
    if not isinstance(report, dict):
        raise ValueError("execution receipt report must be a JSON object")
    answered = _concrete_answers(report)
    rows, key = build_blind_rows(answered, args.seed)

    args.sheet.parent.mkdir(parents=True, exist_ok=True)
    with args.sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["review_id", "question", "model_answer", "correct", "grounded", "notes"],
        )
        writer.writeheader()
        writer.writerows(rows)

    receipt_sha = hashlib.sha256(Path(args.receipt).read_bytes()).hexdigest()
    key_payload = {
        "source_receipt": str(Path(args.receipt).name),
        "source_receipt_sha256": receipt_sha,
        "report_sha256": receipt.get("report_sha256"),
        "audited_commit": report.get("audited_commit"),
        "seed": args.seed,
        "blind_count": len(rows),
        "note": (
            "De-blinding key for the G0 blind review. KEEP SEPARATE from the sheet: "
            "the sheet carries no case_id and no gold label by design."
        ),
        "review_id_to_case_id": key,
    }
    args.key.parent.mkdir(parents=True, exist_ok=True)
    args.key.write_text(
        json.dumps(key_payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "blind_sheet": str(args.sheet),
                "key": str(args.key),
                "blind_count": len(rows),
                "source_receipt_sha256": receipt_sha,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
