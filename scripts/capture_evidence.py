#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required")
    audited_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    qdrant = read_json(ROOT / "qdrant/runtime.lock.json")["qdrant"]
    embedder = read_json(ROOT / "manifests/locks/bge-m3.lock.json")
    reranker = read_json(ROOT / "manifests/locks/bge-reranker-v2-m3.lock.json")
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    header = [
        f"audited_commit: {audited_commit}",
        f"date_utc: {datetime.now(timezone.utc).isoformat()}",
        f"command: {shlex.join(command)}",
        f"exit_code: {result.returncode}",
        f"python_version: {platform.python_version()}",
        f"qdrant_version: {qdrant['version']}",
        f"qdrant_revision: {qdrant['server_commit']}",
        f"embedding_model: {embedder['repo_id']}@{embedder['revision']}",
        f"reranker_model: {reranker['repo_id']}@{reranker['revision']}",
        f"random_seed: {os.environ.get('AUDIT_RANDOM_SEED', 'not_applicable')}",
        "--- stdout ---",
        result.stdout,
        "--- stderr ---",
        result.stderr,
    ]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(header).rstrip() + "\n", encoding="utf-8")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
