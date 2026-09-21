#!/usr/bin/env python3
"""Provisionne un utilisateur local non-root et execute une commande sous lui.

Preuve de durcissement : le harnais RAG peut tourner sans privileges root dans
le PRoot. Usage :
    python scripts/run_local_non_root.py --user hermesrag --workspace /opt/hermesrag \
        --command "python -m unittest discover -s tests"
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from rag_hermes.local_hardening import (
    build_local_user_bootstrap,
    build_local_workload_command,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--command", required=True)
    args = parser.parse_args()

    bootstrap = build_local_user_bootstrap(args.user, args.workspace)
    boot = subprocess.run(["bash", "-c", bootstrap], capture_output=True, text=True)
    if boot.returncode != 0:
        sys.stderr.write(f"bootstrap failed: {boot.stderr}\n")
        return boot.returncode

    workload = build_local_workload_command(args.user, args.command)
    run = subprocess.run(["bash", "-c", workload])
    return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
