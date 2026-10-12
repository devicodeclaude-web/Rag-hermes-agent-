from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from rag_hermes.synthetic_report import (
    build_public_service,
    run_synthetic_evaluation,
)

PINNED_REVISION = "b682a98ab8cb30c4f0561021e0ff9f41e5156526"
PINNED_SHA = "af0631abbffaab14b180abc4531497665a6104d6685328d6abbe53a565c53866"
ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv-audit/bin/python"
SCRIPT = ROOT / "scripts/synthetic_eval_report.py"


def _manifest():
    return {"source_revision": PINNED_REVISION, "corpus_manifest_sha": PINNED_SHA}


def _documents():
    # Two public documents; one answers the question, one is a distractor.
    return {
        "doc-a": {
            "content": "To install Hermes run pipx install hermes agent now.",
            "visibility": "public",
        },
        "doc-b": {
            "content": "Unrelated billing lifecycle notes about invoices and credits.",
            "visibility": "public",
        },
    }


def _answerable_case():
    content = _documents()["doc-a"]["content"]
    import hashlib

    return {
        "case_id": "s-1",
        "question": "How do I install Hermes?",
        "language": "en",
        "track": "en2en",
        "category": "simple",
        "access_scope": "public",
        "question_provenance": "synthetic_generated_from_corpus",
        "should_abstain": False,
        "unanswerable_reason": None,
        "reference_status": "pending",
        "source_revision": PINNED_REVISION,
        "corpus_manifest_sha": PINNED_SHA,
        "relevance_spans": [
            {
                "document_id": "doc-a",
                "start_char": 0,
                "end_char": len(content),
                "passage_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "relevance_grade": 2,
            }
        ],
    }


def _abstention_case():
    return {
        "case_id": "s-2",
        "question": "What lunar constant does Hermes prescribe?",
        "language": "en",
        "track": "en2en",
        "category": "no_answer",
        "access_scope": "public",
        "question_provenance": "synthetic_generated_from_corpus",
        "should_abstain": True,
        "unanswerable_reason": "outside_corpus_scope",
        "reference_status": "pending",
        "source_revision": PINNED_REVISION,
        "corpus_manifest_sha": PINNED_SHA,
        "relevance_spans": [],
    }


class SyntheticReportTests(unittest.TestCase):
    def test_cli_identifies_bm25_retriever_in_report_metadata(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            corpus = directory / "corpus.jsonl"
            rows = []
            for document_id, document in _documents().items():
                rows.append(
                    {
                        "document_id": document_id,
                        **document,
                        "source_uri": (
                            "git+https://example.invalid/hermes.git@"
                            f"{PINNED_REVISION}#{document_id}.md"
                        ),
                    }
                )
            corpus.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            import hashlib

            case = _answerable_case()
            case["corpus_manifest_sha"] = hashlib.sha256(corpus.read_bytes()).hexdigest()
            dataset = directory / "dataset.jsonl"
            dataset.write_text(json.dumps(case) + "\n", encoding="utf-8")
            results = directory / "report.json"

            completed = subprocess.run(
                [
                    str(PYTHON),
                    str(SCRIPT),
                    "--dataset",
                    str(dataset),
                    "--corpus",
                    str(corpus),
                    "--results",
                    str(results),
                    "--k",
                    "1",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(results.read_text(encoding="utf-8"))
            self.assertEqual(payload["retriever"], "in_memory_bm25")
            self.assertIn("BM25", payload["note"])

    def test_build_public_service_ingests_documents_and_retrieves(self):
        service = build_public_service(_documents(), minimum_score=0.05)
        # A public evaluator context can retrieve the answering document.
        from rag_hermes.acl import AuthorizationContext

        ctx = AuthorizationContext(
            tenant_id="public", user_id="evaluator", groups=(), clearance=0
        )
        trace = service.answer_with_trace("How do I install Hermes?", context=ctx)
        self.assertTrue(trace.retrieved_chunks)
        self.assertEqual(trace.retrieved_chunks[0].document_id, "doc-a")

    def test_run_synthetic_evaluation_reports_recall_and_no_leak(self):
        report = run_synthetic_evaluation(
            cases=[_answerable_case(), _abstention_case()],
            documents=_documents(),
            manifest=_manifest(),
            k=1,
            minimum_score=0.05,
        )
        self.assertEqual(report.recall_at_k, 1.0)
        self.assertEqual(report.mrr, 1.0)
        self.assertEqual(report.leak_count, 0)
        self.assertTrue(report.security_gate_passed)
        # The abstention case is scored on the abstention axis.
        self.assertGreaterEqual(report.abstention_recall, 0.0)

    def test_run_synthetic_evaluation_rejects_non_positive_k(self):
        with self.assertRaises(ValueError):
            run_synthetic_evaluation(
                cases=[_answerable_case()],
                documents=_documents(),
                manifest=_manifest(),
                k=0,
                minimum_score=0.05,
            )


if __name__ == "__main__":
    unittest.main()
