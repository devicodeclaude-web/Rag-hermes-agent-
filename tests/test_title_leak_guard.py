from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_title_leak", ROOT / "scripts" / "check_title_leak.py"
)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


class TitleLeakGuardTests(unittest.TestCase):
    def test_tokens_lowercase_alnum(self):
        self.assertEqual(guard.tokens("Adding Providers!"), ["adding", "providers"])

    def test_title_from_frontmatter_then_h1(self):
        self.assertEqual(
            guard.document_title('---\ntitle: "Adding Providers"\n---\n# ignored\n'),
            "Adding Providers",
        )
        self.assertEqual(guard.document_title("# Trajectory Format\nbody"), "Trajectory Format")

    def test_contiguous_sublist(self):
        q = guard.tokens("What does the section 'Adding Providers' explain?")
        self.assertTrue(guard.is_contiguous_sublist(guard.tokens("Adding Providers"), q))
        self.assertFalse(guard.is_contiguous_sublist(guard.tokens("Adding Tools"), q))
        # non-contiguous must not count as a leak
        self.assertFalse(
            guard.is_contiguous_sublist(
                guard.tokens("Adding Providers"),
                guard.tokens("adding first-class support for new model providers"),
            )
        )

    def test_end_to_end_flags_only_the_leaking_case(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = root / "docs.jsonl"
            corpus.write_text(
                "\n".join(
                    json.dumps(record)
                    for record in [
                        {"document_id": "d:leak", "content": '---\ntitle: "Adding Providers"\n---\nbody'},
                        {"document_id": "d:clean", "content": '---\ntitle: "Provider Runtime Resolution"\n---\nbody'},
                    ]
                ),
                encoding="utf-8",
            )
            dataset = root / "set.jsonl"
            dataset.write_text(
                "\n".join(
                    json.dumps(case)
                    for case in [
                        {"case_id": "c1", "question": "What does 'Adding Providers' explain?", "relevant_document_ids": ["d:leak"]},
                        {"case_id": "c2", "question": "How does Hermes resolve credentials at runtime?", "relevant_document_ids": ["d:clean"]},
                        {"case_id": "c3", "question": "no target", "relevant_document_ids": []},
                    ]
                ),
                encoding="utf-8",
            )
            titles = guard.load_titles([corpus])
            self.assertEqual(titles["d:leak"], "Adding Providers")
            leaking = [
                case["case_id"]
                for case in (json.loads(line) for line in dataset.read_text().splitlines())
                for doc_id in case.get("relevant_document_ids", [])
                if guard.is_contiguous_sublist(guard.tokens(titles.get(doc_id, "")), guard.tokens(case["question"]))
            ]
            self.assertEqual(leaking, ["c1"])


if __name__ == "__main__":
    unittest.main()
