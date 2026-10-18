#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from rag_hermes.abstention_calibration import (
    read_repository_json_snapshot,
    repository_file_attestation,
    require_code_revision,
)
from rag_hermes.execution_receipt import run_with_receipt


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data/results"


def _attested_campaign_inputs(manifest: dict[str, object]) -> list[Path]:
    corpus = manifest.get("corpus")
    models = manifest.get("models")
    if not isinstance(corpus, dict) or not isinstance(models, dict):
        raise ValueError("GPU manifest must define corpus and models objects")
    documents = corpus.get("documents")
    questions = corpus.get("questions")
    embedding_lock = models.get("embedding_lock")
    reranker_lock = models.get("reranker_lock")
    if (
        not isinstance(documents, list)
        or not documents
        or any(not isinstance(path, str) or not path for path in documents)
        or not isinstance(questions, str)
        or not questions
        or not isinstance(embedding_lock, str)
        or not embedding_lock
        or not isinstance(reranker_lock, str)
        or not reranker_lock
    ):
        raise ValueError("GPU manifest input paths are invalid")
    candidates = [
        ROOT / "docs/ablation-protocol.md",
        ROOT / questions,
        *(ROOT / path for path in documents),
        ROOT / embedding_lock,
        ROOT / reranker_lock,
    ]
    protected = []
    for candidate in candidates:
        attestation = repository_file_attestation(ROOT, candidate)
        protected.append((ROOT / attestation["path"]).resolve())
    return protected


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the audited GPU campaign and publish its autonomous execution receipt; "
            "the GPU report path is staging non consommable."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "manifests/gpu/bge-m3-human-154.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULTS / "bge_m3_human_154_report.json",
        help="Legacy-compatible staging path; removed after receipt publication.",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=RESULTS / "bge_m3_human_154_execution_receipt.json",
        help="Only final consumable artifact; embeds the complete GPU report.",
    )
    parser.add_argument("--code-revision", required=True)
    args = parser.parse_args()

    revision = require_code_revision(args.code_revision)
    manifest_payload, manifest_attestation = read_repository_json_snapshot(
        ROOT, args.manifest
    )
    manifest = (ROOT / manifest_attestation["path"]).resolve()
    protected_paths = [manifest, *_attested_campaign_inputs(manifest_payload)]
    output = args.output.resolve(strict=False)
    receipt = args.receipt.resolve(strict=False)
    command = [sys.executable, str(ROOT / "scripts/run_bge_gpu_smoke.py")]
    environment = {
        "PYTHONPATH": str(ROOT),
        "PYTHONHASHSEED": "1542026",
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
        "RAG_GPU_MANIFEST": str(manifest),
        "RAG_GPU_MANIFEST_PATH": manifest_attestation["path"],
        "RAG_GPU_MANIFEST_SHA256": manifest_attestation["sha256"],
        "RAG_GPU_OUTPUT": str(output),
        "RAG_CODE_REVISION": revision,
        "RAG_EXECUTION_RECEIPT": str(receipt),
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
