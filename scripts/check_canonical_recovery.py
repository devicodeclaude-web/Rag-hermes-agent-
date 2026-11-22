#!/usr/bin/env python3
"""Vérifier hors ligne une ligne manquante du registre ; ne répare rien.

PYTHONPATH=. python scripts/check_canonical_recovery.py \
  --store /chemin/prive --candidate /chemin/prive/ligne-originale.jsonl
"""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import stat

from rag_hermes.canonical_registry import (
    CanonicalStoreError, verify_anchor_recovery_candidate,
)


def _read_private_candidate(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise CanonicalStoreError("candidate must be a private regular file owned by the operator")
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) & ~os.O_NONBLOCK)
        with os.fdopen(fd, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify_anchor_recovery_candidate(
            args.store, _read_private_candidate(args.candidate)
        )
    except (CanonicalStoreError, OSError) as exc:
        # Aucune donnée documentaire (ni nom de client, ni contenu) dans la sortie.
        print(f"REFUS : {type(exc).__name__} ; aucune modification effectuée")
        return 2
    print("Candidat vérifié contre l'ancre ; aucune modification effectuée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
