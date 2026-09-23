#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements-gpu.lock.txt"
AUDIT_LOCK = ROOT / "requirements-audit.lock.txt"


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("$", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rag-lock-install-") as directory:
        venv = Path(directory) / "venv"
        run([sys.executable, "-m", "venv", str(venv)])
        python = venv / "bin/python"
        run([str(python), "-m", "pip", "install", "--require-hashes", "-r", str(LOCK)])
        run([str(python), "-m", "pip", "install", "--require-hashes", "-r", str(AUDIT_LOCK)])
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        run([str(python), "scripts/run_ci_strict.py"], env=env)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
