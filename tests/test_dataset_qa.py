from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_dataset_qa", ROOT / "scripts" / "check_dataset_qa.py"
)
assert _spec is not None and _spec.loader is not None
qa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qa)


def _write(path: Path, cases: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(c) for c in cases), encoding="utf-8")


class DatasetQaStructureTests(unittest.TestCase):
    def _run_structure(self, cases: list[dict]) -> int:
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "set.jsonl"
            _write(dataset, cases)
            import sys

            argv = sys.argv
            sys.argv = ["qa", "--dataset", str(dataset), "--structure-only"]
            try:
                return qa.main()
            finally:
                sys.argv = argv

    def test_valid_structure_passes(self):
        cases = [
            {"case_id": "a", "category": "simple", "question": "q", "relevant_document_ids": ["d:1"], "distractor_document_ids": ["d:2"], "multi_hop": False},
            {"case_id": "b", "category": "no_answer", "question": "q", "relevant_document_ids": [], "distractor_document_ids": ["d:3"]},
        ]
        self.assertEqual(self._run_structure(cases), 0)

    def test_no_answer_with_target_fails(self):
        cases = [
            {"case_id": "a", "category": "no_answer", "question": "q", "relevant_document_ids": ["d:1"], "distractor_document_ids": []},
        ]
        self.assertEqual(self._run_structure(cases), 1)

    def test_missing_field_fails(self):
        cases = [{"case_id": "a", "category": "simple", "question": "q"}]
        self.assertEqual(self._run_structure(cases), 1)

    def test_duplicate_case_id_fails(self):
        cases = [
            {"case_id": "a", "category": "simple", "question": "q", "relevant_document_ids": ["d:1"], "distractor_document_ids": []},
            {"case_id": "a", "category": "simple", "question": "q2", "relevant_document_ids": ["d:2"], "distractor_document_ids": []},
        ]
        self.assertEqual(self._run_structure(cases), 1)

    def test_multi_hop_inconsistent_fails(self):
        cases = [
            {"case_id": "a", "category": "simple", "question": "q", "relevant_document_ids": ["d:1"], "distractor_document_ids": [], "multi_hop": True},
        ]
        self.assertEqual(self._run_structure(cases), 1)


if __name__ == "__main__":
    unittest.main()
