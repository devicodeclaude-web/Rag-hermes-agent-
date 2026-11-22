#!/usr/bin/env python3
"""Vérifier une ligne manquante ou préparer une copie privée ; jamais la source.

PYTHONPATH=. python scripts/check_canonical_recovery.py \
  --store /chemin/prive --candidate /chemin/prive/ligne-originale.jsonl
# Option : --output-dir /autre/repertoire/prive/reprise
"""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import stat

from rag_hermes.canonical_registry import (
    CanonicalStoreError, verify_anchor_recovery_candidate,
    prepare_anchor_recovery_copy,
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
    parser.add_argument("--output-dir", type=Path,
                        help="nouveau répertoire privé : préparer une COPIE, jamais la source")
    args = parser.parse_args()
    try:
        candidate = _read_private_candidate(args.candidate)
        if args.output_dir is None:
            verify_anchor_recovery_candidate(args.store, candidate)
        else:
            prepare_anchor_recovery_copy(args.store, candidate, args.output_dir)
    except (CanonicalStoreError, OSError) as exc:
        # Une panne après publication peut laisser une copie complète malgré
        # le refus (fsync parent en échec). Ne jamais promettre « aucun écrit ».
        if args.output_dir is None:
            print(f"REFUS : {type(exc).__name__} ; aucune modification effectuée")
        else:
            print(f"REFUS : {type(exc).__name__} ; source inchangée, vérifier la sortie avant toute reprise")
        return 2
    if args.output_dir is None:
        print("Candidat vérifié contre l'ancre ; aucune modification effectuée.")
    else:
        print("Copie de reprise préparée ; source inchangée. NE PAS déployer sans réconciliation Qdrant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
