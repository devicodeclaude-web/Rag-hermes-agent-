import hashlib
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/benchmark/dataset-v1.jsonl"


class LegacyDatasetBuilderTests(unittest.TestCase):
    def test_circular_builder_refuses_default_execution_without_overwriting_dataset(self):
        before = hashlib.sha256(DATASET.read_bytes()).hexdigest()
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/build_dataset_v1.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        after = hashlib.sha256(DATASET.read_bytes()).hexdigest()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("legacy-reproduction-only", completed.stderr)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
