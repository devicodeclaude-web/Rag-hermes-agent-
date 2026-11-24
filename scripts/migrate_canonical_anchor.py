#!/usr/bin/env python3
"""Recréer HORS LIGNE une ancre canonique manquante, gardée par attestation.

Un registre non vide sans ancre échoue fermé au démarrage (anti-recul). Cet
outil republie une ancre UNIQUEMENT si le JSONL courant correspond exactement
à l'attestation indépendante de l'opérateur (compte d'enregistrements et, par
document, doc_version/acl_version), fournie depuis une source EXTERNE à l'hôte.
Il ne reconstruit jamais une ancre à partir du seul fichier : un backup
restauré à des versions plus anciennes est refusé.

À exécuter SERVICE ARRÊTÉ. Ne réconcilie pas Qdrant : l'opérateur doit le faire
séparément avant de remettre le service en route.

PYTHONPATH=. python scripts/migrate_canonical_anchor.py \\
  --store /chemin/prive --attestation /chemin/prive/attestation.json

Format de l'attestation (JSON) :
  {"records": 2, "documents": {"doc-1": {"doc_version": 1, "acl_version": 2}}}
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import stat

from rag_hermes.canonical_registry import (
    CanonicalStoreError,
    bootstrap_canonical_anchor,
)


def _read_private_json(path: Path) -> object:
    """Lire l'attestation comme un fichier privé régulier de l'opérateur."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise CanonicalStoreError(
                "attestation must be a private regular file owned by the operator"
            )
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) & ~os.O_NONBLOCK)
        with os.fdopen(fd, "rb", closefd=False) as handle:
            return json.loads(handle.read().decode("utf-8"))
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    args = parser.parse_args()
    try:
        attestation = _read_private_json(args.attestation)
        bootstrap_canonical_anchor(args.store, attestation)
    except (CanonicalStoreError, OSError, ValueError) as exc:
        # Une publication peut échouer après écriture partielle du temporaire ;
        # l'ancre finale n'est toutefois jamais publiée sans rename réussi.
        print(f"REFUS : {type(exc).__name__}: {exc}")
        print("Ancre non republiée ; vérifier l'attestation et l'état du magasin.")
        return 2
    print(
        "Ancre republiée depuis l'attestation. "
        "NE PAS redémarrer le service sans réconciliation Qdrant."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
