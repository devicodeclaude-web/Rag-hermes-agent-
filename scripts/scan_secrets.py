#!/usr/bin/env python3
"""Scanne tous les fichiers traques par git pour des secrets. Exit 1 si trouve."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rag_hermes.secret_scan import scan_text

ROOT = Path(__file__).resolve().parents[1]
# extensions binaires / donnees a ignorer
SKIP_SUFFIXES = {".pyc", ".mmap", ".dat", ".pack", ".idx", ".jsonl"}
# fichiers qui contiennent LEGITIMEMENT des faux secrets (fixtures de test du
# scanner lui-meme) : les scanner produirait un faux positif circulaire.
SKIP_PATHS = {"tests/test_secret_scan.py"}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line]


def main() -> int:
    findings = []
    for rel in tracked_files():
        if rel in SKIP_PATHS:
            continue
        path = ROOT / rel
        if path.suffix in SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(scan_text(rel, text))

    if findings:
        for f in findings:
            sys.stderr.write(f"SECRET {f.rule} {f.path}:{f.line} {f.preview}\n")
        sys.stderr.write(f"\nECHEC : {len(findings)} secret(s) potentiel(s) trouve(s).\n")
        return 1
    print("OK : aucun secret detecte dans les fichiers traques.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
