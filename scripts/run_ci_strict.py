#!/usr/bin/env python3
"""Exécute la suite en mode CI strict : un test ignoré est un échec.

Ce runner remplace `python -m unittest discover` pour la CI. Il exige que le
service Qdrant réel soit disponible (via QDRANT_INTEGRATION_URL) et transforme
tout `skip` en échec dur, afin qu'un test d'intégration désactivé en silence ne
puisse jamais passer inaperçu.
"""
from __future__ import annotations

import os
import sys
import unittest

from rag_hermes.integration_gate import assert_no_skipped_integration_tests

TESTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")


def main() -> int:
    if not os.environ.get("QDRANT_INTEGRATION_URL"):
        sys.stderr.write(
            "ECHEC CI : QDRANT_INTEGRATION_URL doit pointer vers un Qdrant reel.\n"
        )
        return 2
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
