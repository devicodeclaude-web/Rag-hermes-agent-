#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/benchmark/dataset-v1.jsonl"
EXPECTED = {"simple": 25, "paraphrase": 20, "close_distractor": 20, "chunk_boundary": 15, "no_answer": 20}


def main() -> int:
    raw = DATASET.read_bytes()
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    categories = Counter(item["category"] for item in records)
    human_validated = sum(item["decision_reference_status"] in {"validated", "arbitrated"} for item in records)
    report = {
        "dataset": str(DATASET.relative_to(ROOT)),
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "records": len(records),
        "categories": dict(sorted(categories.items())),
        "expected_categories": EXPECTED,
        "acl_probes": sum(bool(item.get("acl_probe")) for item in records),
        "distractor_miners": sorted({item.get("distractor_miner") for item in records}),
        "human_validated_or_arbitrated": human_validated,
        "initial_manual_control_required": 20,
        "global_quality_conclusion_allowed": human_validated == 100,
        "limitations": [
            "No human validation has been claimed by automation.",
            "The first 20 records are queued for initial manual control only.",
            "No global quality conclusion is allowed before all 100 labels are validated or arbitrated by humans.",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    structural_ok = len(records) == 100 and categories == Counter(EXPECTED) and report["acl_probes"] == 0 and report["distractor_miners"] == ["bm25_stdlib_not_bge_m3"]
    if not structural_ok:
        return 1
    if human_validated < 20:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
