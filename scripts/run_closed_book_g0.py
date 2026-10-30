#!/usr/bin/env python3
"""G0 closed-book (no-retrieval) baseline worker — INFRA/SMOKE, NOT pre-registered.

This is the mandatory no-retrieval baseline of docs/acceptance-criteria.md: the
model answers from its own memory, with no corpus, no sources and no citations.
Because there are no sources, only ONE axis is measurable offline — honest
abstention:
  - required_abstentions    : cases whose should_abstain is True (the 32 no_answer);
  - predicted_abstentions    : cases where the model returned the exact abstention;
  - true_positive_abstentions: cases that both should and did abstain.
Concrete answers on the 122 answerable cases are surfaced by case_id for the
mandatory >=20% blind human review — no offline metric can score their quality.

This run deliberately carries status 'infrastructure_smoke_only': it validates
the G0 wiring and generator endpoint, NOT statistical quality. The generative
quality campaign (G1 RAG vs G0, correctness + citations) and the freeze of
docs/evaluation-protocol-v2.md come AFTER this wiring is validated.

The report is written to RAG_G0_OUTPUT (staging); scripts/run_closed_book_campaign.py
wraps this command with run_with_receipt to publish the only consumable artifact,
the autonomous execution receipt.
"""
from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path
from urllib.parse import urlsplit

from rag_hermes.abstention_calibration import (
    publish_gpu_report_atomic,
    read_clean_repository_revision,
    read_repository_json_snapshot,
    read_repository_snapshot,
    require_clean_code_revision,
)
from rag_hermes.closed_book import ClosedBookGenerator
from rag_hermes.closed_book_eval import ClosedBookReport, run_closed_book_evaluation

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data/results"
MANIFEST = Path(
    os.environ.get("RAG_G0_MANIFEST", ROOT / "manifests/gpu/g0-closed-book-human-154.json")
)
OUTPUT = Path(
    os.environ.get("RAG_G0_OUTPUT", RESULTS / "g0_closed_book_human_154_report.json")
)

# The closed-book generator decodes at temperature 0 / max_tokens 512 (hard-coded
# in rag_hermes.closed_book). The manifest must declare exactly that, so the two
# cannot silently drift.
_REQUIRED_DECODING = {"temperature": 0, "max_tokens": 512}


def load_cases(dataset_payload: bytes) -> list[dict[str, object]]:
    """Project the evaluation-v2 rows onto the (case_id, question, should_abstain)
    triple consumed by the closed-book scorer."""
    cases: list[dict[str, object]] = []
    for line in dataset_payload.decode("utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        should_abstain = row["should_abstain"]
        if type(should_abstain) is not bool:
            raise ValueError(f"{row.get('case_id')}: should_abstain must be a bool")
        cases.append(
            {
                "case_id": str(row["case_id"]),
                "question": str(row["question"]),
                "should_abstain": should_abstain,
            }
        )
    if not cases:
        raise ValueError("G0 dataset is empty")
    return cases


def build_g0_report(
    *,
    manifest: dict[str, object],
    manifest_path: str,
    manifest_sha256: str,
    code_revision: str,
    dataset_attestation: dict[str, str],
    generator_identity: dict[str, object],
    report: ClosedBookReport,
    generation_seconds: float,
) -> dict[str, object]:
    """Assemble the honest G0 report (pure function: no git, no network, no IO)."""
    protocol_raw = manifest.get("protocol")
    protocol: dict[str, object] = protocol_raw if isinstance(protocol_raw, dict) else {}
    return {
        "job_id": manifest["job_id"],
        "code_revision": code_revision,
        "audited_commit": code_revision,
        "configuration": "G0",
        "status": "infrastructure_smoke_only",
        "result_classification": "g0_closed_book_abstention_wiring_not_a_quality_benchmark",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator": generator_identity,
        "protocol": {
            "manifest_path": manifest_path,
            "manifest_sha256": manifest_sha256,
            "dataset_path": dataset_attestation["path"],
            "dataset_sha256": dataset_attestation["sha256"],
            "evaluation_protocol": protocol.get("evaluation_protocol"),
            "evaluation_protocol_status": protocol.get("evaluation_protocol_status"),
            "acceptance_criteria": protocol.get("acceptance_criteria"),
        },
        "corpus": {
            "questions": report.total,
            "track": "human-154",
            "dataset_path": dataset_attestation["path"],
        },
        "generation": {
            "seconds": generation_seconds,
            "temperature": _REQUIRED_DECODING["temperature"],
            "max_tokens": _REQUIRED_DECODING["max_tokens"],
        },
        "metrics_abstention": {
            "total": report.total,
            "required_abstentions": report.required_abstentions,
            "predicted_abstentions": report.predicted_abstentions,
            "true_positive_abstentions": report.true_positive_abstentions,
            "abstention_precision": report.abstention_precision,
            "abstention_recall": report.abstention_recall,
            "generation_failures": report.generation_failures,
        },
        "human_review_sample": {
            "answered_count": len(report.answered_case_ids),
            "answered_case_ids": list(report.answered_case_ids),
            "note": (
                "Mandatory >=20% blind human review judges these concrete answers; "
                "no offline metric scores their correctness."
            ),
        },
        "hardware": {"python": platform.python_version()},
        "quality_gate_passed": False,
        "limitations": [
            "G0 measures ONLY honest abstention (model-alone); answer correctness "
            "on the answerable cases is NOT scored offline and awaits blind human review.",
            "No retrieval, no sources, no citations by design (closed-book baseline).",
            "The served model identity is asserted by the operator via "
            "RAG_GENERATOR_MODEL against the manifest repo_id/revision; vLLM serving "
            "the pinned revision is recorded, not cryptographically proven.",
            "docs/evaluation-protocol-v2.md is a DRAFT; this run is infrastructure "
            "wiring, NOT a pre-registered quality result.",
            "generation_failures are provider errors: neither answers nor abstentions, "
            "and they keep their place in the case total.",
        ],
    }


def main() -> None:
    expected_manifest_sha = os.environ.get("RAG_G0_MANIFEST_SHA256")
    if not expected_manifest_sha:
        raise ValueError("G0 run requires an attested manifest SHA-256 (RAG_G0_MANIFEST_SHA256)")
    manifest, manifest_attestation = read_repository_json_snapshot(
        ROOT, MANIFEST, expected_manifest_sha
    )
    manifest_path = os.environ.get("RAG_G0_MANIFEST_PATH", manifest_attestation["path"])
    if (ROOT / manifest_path).resolve() != MANIFEST.resolve():
        raise ValueError("attested manifest path does not match RAG_G0_MANIFEST")

    generator_manifest = manifest.get("generator")
    if not isinstance(generator_manifest, dict):
        raise ValueError("manifest must define a generator object")
    decoding = generator_manifest.get("decoding")
    if decoding != _REQUIRED_DECODING:
        raise ValueError(
            "manifest generator.decoding must be exactly "
            f"{_REQUIRED_DECODING} to match the closed-book generator"
        )

    code_revision = require_clean_code_revision(
        os.environ.get("RAG_CODE_REVISION"),
        read_clean_repository_revision(ROOT),
        "",
    )

    dataset_rel = manifest["corpus"]["questions"]
    dataset_payload, dataset_attestation = read_repository_snapshot(
        ROOT, ROOT / dataset_rel
    )
    cases = load_cases(dataset_payload)

    base_url = os.environ.get("RAG_GENERATOR_BASE_URL")
    model = os.environ.get("RAG_GENERATOR_MODEL")
    if not base_url or not model:
        raise ValueError(
            "G0 run requires RAG_GENERATOR_BASE_URL and RAG_GENERATOR_MODEL "
            "(OpenAI-compatible endpoint served by vLLM)"
        )
    api_key = os.environ.get("RAG_GENERATOR_API_KEY", "")
    generator = ClosedBookGenerator(base_url=base_url, model=model, api_key=api_key)

    generator_identity = {
        "repo_id": generator_manifest.get("repo_id"),
        "revision": generator_manifest.get("revision"),
        "engine": generator_manifest.get("engine", "vllm"),
        "quantization": generator_manifest.get("quantization"),
        "served_model_name": model,
        "endpoint_host": urlsplit(base_url).hostname,
        "decoding": _REQUIRED_DECODING,
    }

    started = time.monotonic()
    report = run_closed_book_evaluation(cases, generator)
    generation_seconds = time.monotonic() - started

    g0_report = build_g0_report(
        manifest=manifest,
        manifest_path=manifest_path,
        manifest_sha256=manifest_attestation["sha256"],
        code_revision=code_revision,
        dataset_attestation=dataset_attestation,
        generator_identity=generator_identity,
        report=report,
        generation_seconds=generation_seconds,
    )
    publish_gpu_report_atomic(OUTPUT, RESULTS, g0_report)
    print(
        json.dumps(
            {
                "staging_output": str(OUTPUT),
                "total": report.total,
                "required_abstentions": report.required_abstentions,
                "predicted_abstentions": report.predicted_abstentions,
                "abstention_precision": report.abstention_precision,
                "abstention_recall": report.abstention_recall,
                "generation_failures": report.generation_failures,
                "answered_for_review": len(report.answered_case_ids),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
