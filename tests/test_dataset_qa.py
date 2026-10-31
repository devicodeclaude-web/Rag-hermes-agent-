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


class DatasetStatusDocumentationTests(unittest.TestCase):
    def test_status_distinguishes_reviewed_active_298_from_human_154(self):
        active = qa.load_jsonl(ROOT / "data" / "benchmark" / "dataset-v2.jsonl")
        human = qa.load_jsonl(
            ROOT / "data" / "benchmark" / "dataset-v2-human-154.jsonl"
        )
        rejected = qa.load_jsonl(
            ROOT / "data" / "review" / "dataset-v3-rejected.jsonl"
        )
        private_documents = {
            row["document_id"]
            for row in qa.load_jsonl(
                ROOT / "data" / "fixtures" / "private_and_synthetic_documents.jsonl"
            )
        }

        self.assertEqual(len(active), 300)
        self.assertEqual(len({row["case_id"] for row in active}), 300)
        self.assertEqual(
            dict(qa.Counter(row["category"] for row in active)),
            {
                "simple": 76,
                "paraphrase": 60,
                "close_distractor": 60,
                "chunk_boundary": 44,
                "no_answer": 60,
            },
        )
        self.assertEqual(
            {row["case_id"] for row in rejected},
            {"v3na-115", "v3cb-091"},
        )
        self.assertTrue(
            all(row["review_decision"] == "reject" for row in rejected)
        )
        self.assertTrue(
            all(row["manual_review_status"] == "reject" for row in rejected)
        )
        self.assertTrue(
            all(
                row["decision_reference_status"] == "rejected_in_human_review"
                for row in rejected
            )
        )
        self.assertTrue(
            all("rejet" in row["review_note"].lower() for row in rejected)
        )
        self.assertTrue(
            {row["case_id"] for row in active}.isdisjoint(
                {row["case_id"] for row in rejected}
            )
        )
        self.assertTrue(
            all(row["manual_review_status"] == "validated" for row in active)
        )
        self.assertTrue(
            all(row["decision_reference_status"] == "validated" for row in active)
        )
        self.assertTrue(all(row.get("acl_probe") is False for row in active))
        active_targets = {
            document_id
            for row in active
            for document_id in row["relevant_document_ids"]
        }
        self.assertTrue(active_targets.isdisjoint(private_documents))
        self.assertTrue(
            {"track", "language", "question_provenance", "relevance_spans"}
            .isdisjoint(set().union(*(row.keys() for row in active)))
        )
        self.assertTrue(
            {"private", "contradiction", "indirect_injection"}.isdisjoint(
                {row["category"] for row in active}
            )
        )

        self.assertEqual(len(human), 154)
        self.assertEqual(len({row["case_id"] for row in human}), 154)
        self.assertTrue(
            all(
                {"track", "language", "question_provenance", "relevance_spans"}
                <= row.keys()
                for row in human
            )
        )

        status = (ROOT / "docs" / "v1-implementation-status.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("300 cas actifs", status)
        self.assertIn("en attente de revue indépendante", status)
        self.assertIn("154 cas humains", status)
        self.assertIn("privé, contradictions et injections", status)
        self.assertNotIn("146 cas", status)

    def test_protocol_annex_matches_active_dataset_counts(self):
        active = qa.load_jsonl(ROOT / "data" / "benchmark" / "dataset-v2.jsonl")
        categories = qa.Counter(row["category"] for row in active)
        authorship = qa.Counter(row["authorship"] for row in active)
        review_status = qa.Counter(row["manual_review_status"] for row in active)
        reference_status = qa.Counter(
            row["decision_reference_status"] for row in active
        )
        protocol = (ROOT / "docs" / "evaluation-protocol-v2.md").read_text(
            encoding="utf-8"
        )
        annex = protocol.split(
            "## 12. État réel du jeu courant et provenance des questions (annexe)",
            maxsplit=1,
        )[1]

        self.assertIn(f"{len(active)} cas actifs", annex)
        for category, count in categories.items():
            self.assertIn(f"`{category}` {count}", annex)
        for label, count in authorship.items():
            self.assertIn(f"`{label}` : {count}", annex)
        for label, count in review_status.items():
            self.assertIn(f"`{label}` : {count}", annex)
        for label, count in reference_status.items():
            self.assertIn(f"`{label}` : {count}", annex)
        self.assertNotIn("126 cas", annex)
        self.assertNotIn("Les 32 questions", annex)


if __name__ == "__main__":
    unittest.main()
