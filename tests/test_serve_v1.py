from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.serve_v1 import validate_bind_host


ROOT = Path(__file__).resolve().parents[1]


class ServeV1Tests(unittest.TestCase):
    def test_help_documents_local_host_and_port(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/serve_v1.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--host", completed.stdout)
        self.assertIn("--port", completed.stdout)
        self.assertIn("127.0.0.1", completed.stdout)

    def test_bind_host_must_be_loopback(self) -> None:
        self.assertEqual(validate_bind_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(validate_bind_host("localhost"), "localhost")
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "loopback"):
            validate_bind_host("0.0.0.0")

        completed = subprocess.run(
            [sys.executable, "scripts/serve_v1.py", "--host", "0.0.0.0"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("loopback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
