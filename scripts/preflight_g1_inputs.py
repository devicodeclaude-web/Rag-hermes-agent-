#!/usr/bin/env python3
"""Check the *inputs* of a future G1 comparison, never G1 readiness/quality.

No GPU, Qdrant or generation runs here. A passing result says only that the
existing G0 and retrieval receipts refer to the same immutable 154-case set.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from rag_hermes.closed_book import CLOSED_BOOK_ABSTENTION
from rag_hermes.execution_receipt import load_consumable_receipt_v2

ROOT = Path(__file__).resolve().parents[1]
DATASET = "data/benchmark/dataset-v2-human-154.jsonl"
G0 = "data/results/g0_closed_book_human_154_execution_receipt.json"
RETRIEVAL = "data/results/bge_m3_human_154_execution_receipt.json"
G0_MANIFEST = "manifests/gpu/g0-closed-book-human-154.json"
RETRIEVAL_MANIFEST = "manifests/gpu/bge-m3-human-154.json"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _case_ids(rows: object) -> set[str] | None:
    if not isinstance(rows, list):
        return None
    ids = [row.get("case_id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(rows) or any(type(cid) is not str or not cid for cid in ids):
        return None
    unique: set[str] = {cid for cid in ids if isinstance(cid, str)}
    return unique if len(unique) == len(rows) else None


def _report(root: Path, name: str, label: str, blockers: list[str]) -> dict | None:
    path = root / name
    if not path.is_file():
        blockers.append(f"missing_verified_{label}_receipt")
        return None
    try:
        receipt = load_consumable_receipt_v2(path)
    except ValueError:
        blockers.append(f"invalid_{label}_receipt")
        return None
    report = receipt["report"]
    assert isinstance(report, dict)  # guaranteed by the v2 receipt validator
    return report


def _check_snapshot(report: dict, label: str, dataset_sha: str, blockers: list[str]) -> None:
    protocol = report.get("protocol")
    if (
        not isinstance(protocol, dict)
        or protocol.get("dataset_path") != DATASET
        or protocol.get("dataset_sha256") != dataset_sha
    ):
        blockers.append(f"{label}_dataset_mismatch")
    revision = report.get("code_revision")
    if (type(revision) is not str
            or re.fullmatch(r"[0-9a-f]{40}", revision) is None
            or revision != report.get("audited_commit")):
        blockers.append(f"{label}_revision_mismatch")


def _check_manifest(
    root: Path, report: dict, label: str, path: str, blockers: list[str]
) -> dict | None:
    try:
        raw = (root / path).read_bytes()
        manifest = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
        if not isinstance(manifest, dict) or manifest["corpus"]["questions"] != DATASET:
            raise ValueError("manifest is not for this dataset")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        blockers.append(f"invalid_{label}_manifest")
        return None
    protocol = report.get("protocol")
    if (
        not isinstance(protocol, dict)
        or protocol.get("manifest_path") != path
        or protocol.get("manifest_sha256") != hashlib.sha256(raw).hexdigest()
    ):
        blockers.append(f"{label}_manifest_mismatch")
    return manifest


def check_g1_inputs(root: Path = ROOT) -> dict[str, object]:
    """Return explicit blockers; input alignment never implies operational G1."""
    blockers: list[str] = []
    dataset_ids: set[str] | None = None
    dataset_rows: dict[str, dict] = {}
    dataset_sha = ""
    try:
        dataset_bytes = (root / DATASET).read_bytes()
        dataset_sha = hashlib.sha256(dataset_bytes).hexdigest()
        rows = [json.loads(line) for line in dataset_bytes.decode("utf-8").splitlines() if line.strip()]
        dataset_ids = _case_ids(rows)
        if dataset_ids is not None:
            dataset_rows = {row["case_id"]: row for row in rows}
    except (OSError, UnicodeError, ValueError):
        pass
    if dataset_ids is None or len(dataset_ids) != 154:
        blockers.append("invalid_human_154_dataset")

    retrieval = _report(root, RETRIEVAL, "retrieval", blockers)
    g0 = _report(root, G0, "g0", blockers)
    if dataset_ids is not None and len(dataset_ids) == 154:
        if retrieval is not None:
            _check_snapshot(retrieval, "retrieval", dataset_sha, blockers)
            _check_manifest(root, retrieval, "retrieval", RETRIEVAL_MANIFEST, blockers)
            if retrieval.get("status") != "intermediate_human_component_evaluation":
                blockers.append("retrieval_report_status_mismatch")
            if _case_ids(retrieval.get("cases")) != dataset_ids:
                blockers.append("retrieval_cases_mismatch")
        if g0 is not None:
            _check_snapshot(g0, "g0", dataset_sha, blockers)
            manifest = _check_manifest(root, g0, "g0", G0_MANIFEST, blockers)
            if g0.get("configuration") != "G0":
                blockers.append("g0_configuration_mismatch")
            if g0.get("status") != "infrastructure_smoke_only":
                blockers.append("g0_report_status_mismatch")
            if (g0.get("result_classification") !=
                "g0_closed_book_abstention_wiring_not_a_quality_benchmark"
                or g0.get("quality_gate_passed") is not False):
                blockers.append("g0_classification_mismatch")
            corpus = g0.get("corpus")
            if (not isinstance(corpus, dict)
                or type(corpus.get("questions")) is not int
                or corpus["questions"] != len(dataset_ids)
                or corpus.get("track") != "human-154"
                or corpus.get("dataset_path") != DATASET):
                blockers.append("g0_corpus_mismatch")
            records = g0.get("answer_records")
            metrics = g0.get("metrics_abstention")
            if (
                not isinstance(records, list)
                or _case_ids(records) != dataset_ids
                or not isinstance(metrics, dict)
                or type(metrics.get("generation_failures")) is not int
                or metrics["generation_failures"] != 0
                or type(metrics.get("total")) is not int
                or metrics["total"] != len(dataset_ids)
                or any(
                    type(record.get("question")) is not str
                    or record["question"] != dataset_rows[record["case_id"]].get("question")
                    or type(record.get("should_abstain")) is not bool
                    or record["should_abstain"] is not dataset_rows[record["case_id"]].get("should_abstain")
                    or type(record.get("answer")) is not str
                    or not record["answer"].strip()
                    or type(record.get("did_abstain")) is not bool
                    or record["did_abstain"] != (record["answer"].strip() == CLOSED_BOOK_ABSTENTION)
                    for record in (records if isinstance(records, list) else [])
                )
                or any(type(metrics.get(key)) is not int for key in (
                    "required_abstentions", "predicted_abstentions", "true_positive_abstentions"
                ))
                or metrics["required_abstentions"] != sum(row["should_abstain"] for row in records)
                or metrics["predicted_abstentions"] != sum(row["did_abstain"] for row in records)
                or metrics["true_positive_abstentions"] != sum(
                    row["should_abstain"] and row["did_abstain"] for row in records
                )
                or type(metrics.get("abstention_precision")) not in (int, float)
                or type(metrics.get("abstention_recall")) not in (int, float)
                or metrics["abstention_precision"] != (
                    metrics["true_positive_abstentions"] / metrics["predicted_abstentions"]
                    if metrics["predicted_abstentions"] else 0.0
                )
                or metrics["abstention_recall"] != (
                    metrics["true_positive_abstentions"] / metrics["required_abstentions"]
                    if metrics["required_abstentions"] else 0.0
                )
            ):
                blockers.append("g0_answer_capture_incomplete")
            sample = g0.get("human_review_sample")
            if isinstance(records, list) and _case_ids(records) == dataset_ids and all(
                type(row.get("did_abstain")) is bool for row in records
            ):
                answered = {row["case_id"] for row in records if not row["did_abstain"]}
                sample_ids = sample.get("answered_case_ids") if isinstance(sample, dict) else None
                if (not isinstance(sample, dict)
                    or not isinstance(sample_ids, list)
                    or any(type(cid) is not str for cid in sample_ids)
                    or len(sample_ids) != len(set(sample_ids))
                    or set(sample_ids) != answered
                    or type(sample.get("answered_count")) is not int
                    or sample["answered_count"] != len(answered)):
                    blockers.append("g0_review_sample_mismatch")
            if manifest is not None:
                protocol_pin = manifest.get("protocol")
                if (manifest.get("classification") != "infrastructure_smoke_only"
                    or not isinstance(protocol_pin, dict)
                    or protocol_pin.get("configuration") != "G0"):
                    blockers.append("g0_manifest_configuration_mismatch")
                pin = manifest.get("generator")
                identity = g0.get("generator")
                generation = g0.get("generation")
                required = ("repo_id", "revision", "engine", "quantization", "served_model_name")
                if (not isinstance(pin, dict) or not isinstance(identity, dict)
                    or any(type(pin.get(key)) is not str or not pin[key] for key in required)
                    or pin.get("decoding") != {"temperature": 0, "max_tokens": 512}
                    or not isinstance(generation, dict)
                    or type(generation.get("temperature")) is not int
                    or generation["temperature"] != 0
                    or type(generation.get("max_tokens")) is not int
                    or generation["max_tokens"] != 512
                    or any(
                    identity.get(key) != pin.get(key)
                    for key in (*required, "decoding")
                    )):
                    blockers.append("g0_generator_pin_mismatch")
    return {
        "scope": "input_alignment_only_not_g1_readiness",
        "inputs_aligned": not blockers,
        "dataset_cases": len(dataset_ids) if dataset_ids is not None else None,
        "dataset_sha256": dataset_sha if dataset_ids is not None else None,
        "blockers": blockers,
    }


def main() -> int:
    result = check_g1_inputs()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["inputs_aligned"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
