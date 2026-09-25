import io
import unittest
from unittest.mock import patch

import scripts.run_ci_strict as run_ci_strict


class StrictCiSecretScannerTests(unittest.TestCase):
    def test_missing_gitleaks_is_a_hard_failure(self):
        stderr = io.StringIO()
        with (
            patch.object(run_ci_strict.shutil, "which", return_value=None),
            patch.object(run_ci_strict.os.path, "exists", return_value=False),
            patch.object(run_ci_strict.sys, "stderr", stderr),
        ):
            result = run_ci_strict.run_gitleaks()

        self.assertNotEqual(result, 0)
        self.assertIn("ECHEC CI", stderr.getvalue())
        self.assertIn("gitleaks absent", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
