#!/usr/bin/env python3
"""Exécute la suite en mode CI strict : un test ignoré est un échec.

Ce runner remplace `python -m unittest discover` pour la CI. Il exige que le
service Qdrant réel soit disponible (via QDRANT_INTEGRATION_URL) et transforme
tout `skip` en échec dur, afin qu'un test d'intégration désactivé en silence ne
puisse jamais passer inaperçu.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rag_hermes.integration_gate import assert_no_skipped_integration_tests

TESTS_DIR = os.path.join(ROOT, "tests")


GITLEAKS_BIN_ENV = "GITLEAKS_BIN"
# Fixtures the strict suite cannot run without. A missing one used to surface
# late and opaquely as "integration tests skipped"; name it up front instead.
REQUIRED_FIXTURE_ENV = (
    "QDRANT_INTEGRATION_URL",
    "QDRANT_AUTH_INTEGRATION_URL",
    "QDRANT_AUTH_ADMIN_KEY",
)


def missing_fixture_env() -> list[str]:
    return [
        name for name in REQUIRED_FIXTURE_ENV
        if not os.environ.get(name, "").strip()
    ]


def resolve_gitleaks() -> str | None:
    """Résout le binaire gitleaks sans repli implicite.

    L'ancien code se rabattait sur `/tmp/gitleaks` : n'importe quel processus
    local pouvait y déposer un faux scanner que la CI aurait exécuté en
    croyant scanner l'historique. Le binaire doit donc venir du `PATH` ou
    d'un chemin explicitement déclaré via `GITLEAKS_BIN`.
    """
    explicit = os.environ.get(GITLEAKS_BIN_ENV, "").strip()
    if explicit:
        if os.path.isfile(explicit) and os.access(explicit, os.X_OK):
            return explicit
        return None
    return shutil.which("gitleaks")


def run_gitleaks() -> int:
    """Scanne tout l'historique git. Un scanner absent est un échec dur."""
    binary = resolve_gitleaks()
    if binary is None:
        sys.stderr.write(
            "ECHEC CI : gitleaks absent, scan de secrets historique impossible.\n"
            f"Mets le binaire dans le PATH ou declare {GITLEAKS_BIN_ENV}=<chemin>.\n"
            "Aucun repli sur un chemin monde-inscriptible (/tmp) n'est accepte.\n"
        )
        return 5
    config = os.path.join(ROOT, ".gitleaks.toml")
    result = subprocess.run(
        # --redact : un vrai secret trouve ne doit JAMAIS etre recopie dans le
        # journal CI, qui peut etre public.
        [binary, "git", "--no-banner", "--redact", f"--config={config}", ROOT],
        capture_output=True,
        text=True,
    )
    # Le resume (nombre de commits scannes) est la SEULE preuve que le scan a
    # couvert l'historique et non un clone superficiel d'un seul commit : il
    # est donc toujours consigne, succes ou echec.
    summary = "\n".join(
        line for line in result.stderr.splitlines()
        if "commits scanned" in line or "leaks found" in line or "no leaks found" in line
    )
    if result.returncode != 0:
        sys.stderr.write(summary + "\n")
        sys.stderr.write(
            "ECHEC CI : gitleaks a trouve des secrets. Resultats non recopies "
            "ici pour ne pas divulguer la valeur ; rejoue le scan en local.\n"
        )
    else:
        sys.stdout.write(summary + "\n")
    return result.returncode


def main() -> int:
    missing = missing_fixture_env()
    if missing:
        sys.stderr.write(
            "ECHEC CI : variables de fixture manquantes : "
            + ", ".join(missing)
            + ".\nQDRANT_INTEGRATION_URL doit pointer vers un Qdrant reel ; "
            "QDRANT_AUTH_INTEGRATION_URL et QDRANT_AUTH_ADMIN_KEY vers une "
            "instance avec authentification et jwt_rbac (tests SEC-03).\n"
        )
        return 2
    gitleaks_rc = run_gitleaks()
    if gitleaks_rc != 0:
        return 4
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=TESTS_DIR, pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    try:
        assert_no_skipped_integration_tests(result, expected_tests=result.testsRun)
    except RuntimeError as error:
        sys.stderr.write(f"ECHEC CI : {error}\n")
        return 3
    if not result.wasSuccessful():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
