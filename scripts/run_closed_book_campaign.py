#!/usr/bin/env python3
"""Run the G0 closed-book baseline and publish its autonomous execution receipt.

Mirrors scripts/run_bge_gpu_campaign.py: the G0 worker writes a staging report to
RAG_G0_OUTPUT, and run_with_receipt turns it into the only consumable artifact,
a self-verifying execution receipt (gpu_execution_receipt.v2).

The OpenAI-compatible generator endpoint must be reachable from this process:
  export RAG_GENERATOR_BASE_URL=http://127.0.0.1:8000/v1   # local vLLM
  export RAG_GENERATOR_MODEL=qwen2.5-7b-instruct            # served model name
  # optional, never recorded in the receipt:
  export RAG_GENERATOR_API_KEY=...

base_url and model are recorded in the receipt environment for provenance; the
API key is inherited from the ambient environment and is deliberately NOT part of
the audited environment dict.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rag_hermes.abstention_calibration import (
    read_repository_json_snapshot,
    repository_file_attestation,
    require_code_revision,
)
from rag_hermes.execution_receipt import run_with_receipt

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data/results"


def _attested_g0_inputs(manifest: dict[str, object]) -> list[Path]:
    corpus = manifest.get("corpus")
    if not isinstance(corpus, dict):
        raise ValueError("G0 manifest must define a corpus object")
    questions = corpus.get("questions")
    if not isinstance(questions, str) or not questions:
        raise ValueError("G0 manifest corpus.questions is invalid")
    protected: list[Path] = []
    for candidate in (ROOT / questions,):
        attestation = repository_file_attestation(ROOT, candidate)
        protected.append((ROOT / attestation["path"]).resolve())
    return protected


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the G0 closed-book baseline and publish its autonomous execution "
            "receipt; the staging report path is non consommable."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "manifests/gpu/g0-closed-book-human-154.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULTS / "g0_closed_book_human_154_report.json",
        help="Staging path; removed after receipt publication.",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=RESULTS / "g0_closed_book_human_154_execution_receipt.json",
        help="Only final consumable artifact; embeds the complete G0 report.",
    )
    parser.add_argument("--code-revision", required=True)
    args = parser.parse_args()

    revision = require_code_revision(args.code_revision)
    manifest_payload, manifest_attestation = read_repository_json_snapshot(
        ROOT, args.manifest
    )
    manifest = (ROOT / manifest_attestation["path"]).resolve()
    protected_paths = [manifest, *_attested_g0_inputs(manifest_payload)]
    output = args.output.resolve(strict=False)
    receipt = args.receipt.resolve(strict=False)

    base_url = os.environ.get("RAG_GENERATOR_BASE_URL")
    model = os.environ.get("RAG_GENERATOR_MODEL")
    if not base_url or not model:
        raise SystemExit(
            "set RAG_GENERATOR_BASE_URL and RAG_GENERATOR_MODEL before running "
            "(OpenAI-compatible endpoint served by vLLM)"
        )

    command = [sys.executable, str(ROOT / "scripts/run_closed_book_g0.py")]
    environment = {
        "PYTHONPATH": str(ROOT),
        "PYTHONHASHSEED": "1542026",
        "RAG_G0_MANIFEST": str(manifest),
        "RAG_G0_MANIFEST_PATH": manifest_attestation["path"],
        "RAG_G0_MANIFEST_SHA256": manifest_attestation["sha256"],
        "RAG_G0_OUTPUT": str(output),
        "RAG_CODE_REVISION": revision,
        "RAG_EXECUTION_RECEIPT": str(receipt),
        # Recorded in the receipt for provenance (never the API key):
        "RAG_GENERATOR_BASE_URL": base_url,
        "RAG_GENERATOR_MODEL": model,
    }
    return run_with_receipt(
        command,
        cwd=ROOT,
        environment=environment,
        report_path=output,
        receipt_path=receipt,
        approved_results_directory=RESULTS,
        protected_paths=protected_paths,
    )


if __name__ == "__main__":
    raise SystemExit(main())
