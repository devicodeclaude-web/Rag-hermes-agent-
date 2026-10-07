from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv-audit/bin/python"
SCRIPT = ROOT / "scripts/dense_eval_report.py"
PINNED_REVISION = "b682a98ab8cb30c4f0561021e0ff9f41e5156526"


def _write_inputs(directory: Path, *, synthetic: bool = False) -> tuple[Path, Path]:
    corpus = directory / "corpus.jsonl"
    content = "alpha install Hermes with pipx omega reduce token usage by compression"
    document = {
        "document_id": "guide",
        "content": content,
        "visibility": "public",
        "source_uri": f"git+https://example.invalid/hermes.git@{PINNED_REVISION}#guide.md",
    }
    corpus.write_text(json.dumps(document) + "\n", encoding="utf-8")
    corpus_sha = hashlib.sha256(corpus.read_bytes()).hexdigest()
    passage = "install Hermes with pipx"
    start = content.index(passage)
    case = {
        "case_id": "dense-1",
        "question": "How do I install Hermes?",
        "language": "en",
        "track": "en2en",
        "category": "simple",
        "access_scope": "public",
        "question_provenance": (
            "synthetic_generated_from_corpus"
            if synthetic
            else "human_task_without_corpus_view"
        ),
        "should_abstain": False,
        "unanswerable_reason": None,
        "reference_status": "validated",
        "source_revision": PINNED_REVISION,
        "corpus_manifest_sha": corpus_sha,
        "relevance_spans": [
            {
                "document_id": "guide",
                "start_char": start,
                "end_char": start + len(passage),
                "passage_sha256": hashlib.sha256(passage.encode()).hexdigest(),
                "relevance_grade": 2,
            }
        ],
    }
    dataset = directory / "dataset.jsonl"
    dataset.write_text(json.dumps(case) + "\n", encoding="utf-8")
    return dataset, corpus


def _run(dataset, corpus, results, checksum):
    return subprocess.run(
        [
            str(PYTHON),
            str(SCRIPT),
            "--dataset", str(dataset),
            "--corpus", str(corpus),
            "--results", str(results),
            "--checksum", str(checksum),
            "--qdrant-url", os.environ["QDRANT_INTEGRATION_URL"],
            "--k", "5",
            "--minimum-score", "0.0",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
    )


@unittest.skipUnless(
    os.environ.get("QDRANT_INTEGRATION_URL"), "Qdrant integration disabled"
)
class DenseEvalReportCliTests(unittest.TestCase):
    def test_success_writes_honestly_labeled_report_and_matching_checksum(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset, corpus = _write_inputs(directory)
            results = directory / "report.json"
            checksum = directory / "report.sha256"

            completed = _run(dataset, corpus, results, checksum)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(results.read_text(encoding="utf-8"))
            self.assertEqual(payload["track"], "dense")
            # Deterministic plumbing: NO semantic quality claim.
            self.assertFalse(payload["quality_eligible"])
            self.assertEqual(payload["retriever"], "qdrant_deterministic_not_an_embedding")
            self.assertIsNone(payload["embedding_model"])
            self.assertTrue(payload["qdrant_exercised"])
            self.assertEqual(payload["cases_total"], 1)
            expected = hashlib.sha256(results.read_bytes()).hexdigest()
            self.assertEqual(checksum.read_text(encoding="utf-8").strip(), expected)

    def test_failure_removes_stale_report_and_checksum(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset, corpus = _write_inputs(directory, synthetic=True)
            results = directory / "report.json"
            checksum = directory / "report.sha256"
            results.write_text("STALE_REPORT", encoding="utf-8")
            checksum.write_text("STALE_CHECKSUM", encoding="utf-8")

            completed = _run(dataset, corpus, results, checksum)

            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(results.exists())
            self.assertFalse(checksum.exists())
            self.assertTrue(dataset.exists())
            self.assertTrue(corpus.exists())


if __name__ == "__main__":
    unittest.main()
