#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import threading
from typing import Callable, Mapping

from rag_hermes.abstention_calibration import require_code_revision
from rag_hermes.execution_receipt import validate_consumable_receipt_v2


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data/results"
MAX_RECEIPT_BYTES = 8 * 1024 * 1024
CAMPAIGN_TIMEOUT_SECONDS = 19 * 60
_CAMPAIGN_LOCK = threading.Lock()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _validated_revision(job: object) -> str:
    if (
        not isinstance(job, dict)
        or "input" not in job
        or not set(job).issubset({"id", "input"})
        or ("id" in job and (not isinstance(job["id"], str) or not job["id"]))
    ):
        raise ValueError("serverless job must contain input and an optional non-empty id")
    payload = job["input"]
    if not isinstance(payload, dict) or set(payload) != {"code_revision"}:
        raise ValueError("serverless input must contain exactly code_revision")
    return require_code_revision(payload["code_revision"])


def _read_bounded_receipt(path: Path) -> dict[str, object]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("campaign receipt must be a regular file")
        if metadata.st_size > MAX_RECEIPT_BYTES:
            raise RuntimeError("campaign receipt exceeds the Serverless output budget")
        blocks: list[bytes] = []
        remaining = MAX_RECEIPT_BYTES + 1
        while remaining > 0:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            blocks.append(block)
            remaining -= len(block)
        encoded = b"".join(blocks)
        if len(encoded) > MAX_RECEIPT_BYTES:
            raise RuntimeError("campaign receipt exceeds the Serverless output budget")
        try:
            payload = json.loads(
                encoded.decode("utf-8"), parse_constant=_reject_json_constant
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("campaign receipt is not strict JSON") from exc
        return validate_consumable_receipt_v2(payload)
    finally:
        os.close(descriptor)


def _discard_artifact(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except IsADirectoryError:
        pass


def _run_in_process_group(
    command: list[str],
    *,
    cwd: Path,
    timeout: float,
    check: bool = False,
) -> subprocess.CompletedProcess[object]:
    process = subprocess.Popen(command, cwd=cwd, start_new_session=True)
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise subprocess.TimeoutExpired(
            command, timeout, output=exc.output, stderr=exc.stderr
        ) from exc
    completed: subprocess.CompletedProcess[object] = subprocess.CompletedProcess(
        command, return_code
    )
    if check:
        completed.check_returncode()
    return completed


def _run_campaign_job_locked(
    job: object,
    *,
    root: Path = ROOT,
    runner: Callable[..., subprocess.CompletedProcess[object]] = _run_in_process_group,
    revision_validator: Callable[[object], str] = require_code_revision,
) -> dict[str, object]:
    revision = _validated_revision(job)
    revision = revision_validator(revision)
    results = root / "data/results"
    manifest = root / "manifests/gpu/bge-m3-human-154.json"
    staging = results / "bge_m3_human_154_report.json"
    receipt_path = results / "bge_m3_human_154_execution_receipt.json"
    command = [
        sys.executable,
        "-m",
        "scripts.run_bge_gpu_campaign",
        "--manifest",
        str(manifest),
        "--output",
        str(staging),
        "--receipt",
        str(receipt_path),
        "--code-revision",
        revision,
    ]
    try:
        completed = runner(
            command,
            cwd=root,
            check=False,
            timeout=CAMPAIGN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        _discard_artifact(staging)
        _discard_artifact(receipt_path)
        raise RuntimeError("campaign exceeded the local Serverless time budget") from exc
    except Exception:
        _discard_artifact(staging)
        _discard_artifact(receipt_path)
        raise
    if completed.returncode != 0:
        _discard_artifact(staging)
        _discard_artifact(receipt_path)
        raise RuntimeError(f"campaign failed with exit code {completed.returncode}")

    try:
        receipt = _read_bounded_receipt(receipt_path)
        environment = receipt["environment"]
        report = receipt["report"]
        if (
            not isinstance(environment, Mapping)
            or environment.get("RAG_CODE_REVISION") != revision
            or not isinstance(report, Mapping)
            or report.get("code_revision") != revision
            or report.get("audited_commit") != revision
        ):
            raise RuntimeError("campaign receipt revision mismatch")
        return receipt
    except Exception:
        _discard_artifact(staging)
        _discard_artifact(receipt_path)
        raise


def run_campaign_job(
    job: object,
    *,
    root: Path = ROOT,
    runner: Callable[..., subprocess.CompletedProcess[object]] = _run_in_process_group,
    revision_validator: Callable[[object], str] = require_code_revision,
) -> dict[str, object]:
    if not _CAMPAIGN_LOCK.acquire(blocking=False):
        raise RuntimeError("a GPU campaign is already running on this worker")
    try:
        return _run_campaign_job_locked(
            job,
            root=root,
            runner=runner,
            revision_validator=revision_validator,
        )
    finally:
        _CAMPAIGN_LOCK.release()


def handler(job: object) -> dict[str, object]:
    return run_campaign_job(job)


def main() -> None:
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
