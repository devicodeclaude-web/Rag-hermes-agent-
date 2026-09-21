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

from rag_hermes.integration_gate import assert_no_skipped_integration_tests

TESTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_gitleaks() -> int:
    """Scanne tout l'historique git. Absent -> avertissement non bloquant."""
    binary = shutil.which("gitleaks") or "/tmp/gitleaks"
    if not (shutil.which("gitleaks") or os.path.exists("/tmp/gitleaks")):
        sys.stderr.write(
            "AVERTISSEMENT CI : gitleaks absent, scan de secrets historique ignore.\n"
        )
        return 0
    config = os.path.join(ROOT, ".gitleaks.toml")
    result = subprocess.run(
        [binary, "git", "--no-banner", f"--config={config}", ROOT],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        sys.stderr.write("ECHEC CI : gitleaks a trouve des secrets.\n")
    return result.returncode


def main() -> int:
    if not os.environ.get("QDRANT_INTEGRATION_URL"):
        sys.stderr.write(
            "ECHEC CI : QDRANT_INTEGRATION_URL doit pointer vers un Qdrant reel.\n"
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
