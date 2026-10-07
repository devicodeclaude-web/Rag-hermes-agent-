from __future__ import annotations

import hashlib
import io
import json
import os
from contextlib import redirect_stderr
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import human_eval_report as report_cli

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv-audit/bin/python"
SCRIPT = ROOT / "scripts/human_eval_report.py"
PINNED_REVISION = "b682a98ab8cb30c4f0561021e0ff9f41e5156526"


def _write_inputs(
    directory: Path,
    *,
    synthetic: bool = False,
    provenance: str = "human_task_without_corpus_view",
) -> tuple[Path, Path]:
    corpus = directory / "corpus.jsonl"
    content = "alpha install Hermes with pipx omega"
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
        "case_id": "human-1",
        "question": "How do I install Hermes?",
        "language": "en",
        "track": "en2en",
        "category": "simple",
        "access_scope": "public",
        "question_provenance": (
            "synthetic_generated_from_corpus" if synthetic else provenance
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


def _run(dataset: Path, corpus: Path, results: Path, checksum: Path):
    return subprocess.run(
        [
            str(PYTHON),
            str(SCRIPT),
            "--dataset",
            str(dataset),
            "--corpus",
            str(corpus),
            "--results",
            str(results),
            "--checksum",
            str(checksum),
            "--k",
            "1",
            "--minimum-score",
            "0.05",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )


class HumanEvalReportCliTests(unittest.TestCase):
    def test_success_writes_report_and_matching_checksum(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset, corpus = _write_inputs(directory)
            results = directory / "report.json"
            checksum = directory / "report.sha256"

            completed = _run(dataset, corpus, results, checksum)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(results.read_text(encoding="utf-8"))
            self.assertEqual(payload["track"], "human")
            self.assertTrue(payload["quality_eligible"])
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

    def test_output_aliasing_input_is_refused_without_deleting_input(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset, corpus = _write_inputs(directory)
            original = dataset.read_bytes()
            checksum = directory / "report.sha256"

            completed = _run(dataset, corpus, dataset, checksum)

            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(dataset.read_bytes(), original)
            self.assertFalse(checksum.exists())
    def test_hardlink_output_alias_to_input_is_refused_without_deletion(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset, corpus = _write_inputs(directory)
            original = dataset.read_bytes()
            results = directory / "report.json"
            subprocess.run(["ln", str(dataset), str(results)], check=True)
            checksum = directory / "report.sha256"

            completed = _run(dataset, corpus, results, checksum)

            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(dataset.read_bytes(), original)
            self.assertEqual(results.read_bytes(), original)
            self.assertFalse(checksum.exists())

    def test_invalid_argument_removes_stale_outputs(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset, corpus = _write_inputs(directory)
            results = directory / "report.json"
            checksum = directory / "report.sha256"
            results.write_text("STALE_REPORT", encoding="utf-8")
            checksum.write_text("STALE_CHECKSUM", encoding="utf-8")

            completed = subprocess.run(
                [
                    str(PYTHON), str(SCRIPT),
                    "--dataset", str(dataset),
                    "--corpus", str(corpus),
                    "--results", str(results),
                    "--checksum", str(checksum),
                    "--k", "not-an-integer",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(results.exists())
            self.assertFalse(checksum.exists())
            self.assertTrue(dataset.exists())
            self.assertTrue(corpus.exists())

    def test_help_does_not_invalidate_outputs(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            results = directory / "report.json"
            checksum = directory / "report.sha256"
            results.write_text("CURRENT_REPORT", encoding="utf-8")
            checksum.write_text("CURRENT_CHECKSUM", encoding="utf-8")

            completed = subprocess.run(
                [
                    str(PYTHON), str(SCRIPT), "--help",
                    "--results", str(results),
                    "--checksum", str(checksum),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
            )

            self.assertEqual(completed.returncode, 0)
            self.assertEqual(results.read_text(), "CURRENT_REPORT")
            self.assertEqual(checksum.read_text(), "CURRENT_CHECKSUM")
    def test_missing_path_value_still_invalidates_recovered_outputs(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset, corpus = _write_inputs(directory)
            results = directory / "report.json"
            checksum = directory / "report.sha256"
            results.write_text("STALE_REPORT", encoding="utf-8")
            checksum.write_text("STALE_CHECKSUM", encoding="utf-8")

            completed = subprocess.run(
                [
                    str(PYTHON), str(SCRIPT),
                    "--dataset", str(dataset),
                    "--corpus", str(corpus),
                    "--results", str(results),
                    "--checksum", str(checksum),
                    "--results",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(results.exists())
            self.assertFalse(checksum.exists())
            self.assertTrue(dataset.exists())
            self.assertTrue(corpus.exists())

    def test_first_unlink_failure_leaves_marker_and_processes_second_output(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            first = directory / "report.json"
            second = directory / "report.sha256"
            first.write_text("STALE_REPORT", encoding="utf-8")
            second.write_text("STALE_CHECKSUM", encoding="utf-8")

            real_unlink = Path.unlink
            calls = 0

            def fail_first(path, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PermissionError("blocked")
                return real_unlink(path, *args, **kwargs)

            with mock.patch.object(Path, "unlink", autospec=True, side_effect=fail_first):
                with self.assertRaises(OSError):
                    report_cli._invalidate((first, second))

            self.assertEqual(
                json.loads(first.read_text(encoding="utf-8"))["status"],
                "INVALIDATED",
            )
            self.assertFalse(second.exists())

    def test_second_unlink_failure_leaves_non_consumable_marker(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            first = directory / "report.json"
            second = directory / "report.sha256"
            first.write_text("STALE_REPORT", encoding="utf-8")
            second.write_text("STALE_CHECKSUM", encoding="utf-8")

            real_unlink = Path.unlink
            calls = 0

            def fail_second(path, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise PermissionError("blocked")
                return real_unlink(path, *args, **kwargs)

            with mock.patch.object(Path, "unlink", autospec=True, side_effect=fail_second):
                with self.assertRaises(OSError):
                    report_cli._invalidate((first, second))

            self.assertFalse(first.exists())
            self.assertEqual(
                json.loads(second.read_text(encoding="utf-8"))["status"],
                "INVALIDATED",
            )

    def test_interruption_before_report_commit_leaves_no_current_report(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            results = directory / "report.json"
            checksum = directory / "report.sha256"
            report_bytes = b'{"status":"complete"}\n'
            digest_bytes = hashlib.sha256(report_bytes).hexdigest().encode("ascii") + b"\n"
            real_replace = os.replace

            def interrupt_on_report(source, destination):
                if Path(destination) == results:
                    raise KeyboardInterrupt("simulated abrupt stop")
                return real_replace(source, destination)

            with mock.patch.object(
                report_cli.os,
                "replace",
                side_effect=interrupt_on_report,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    report_cli._publish_artifacts(
                        results,
                        report_bytes,
                        checksum,
                        digest_bytes,
                    )

            self.assertFalse(results.exists())
            self.assertEqual(checksum.read_bytes(), digest_bytes)

    def test_reports_anonymized_and_mixed_provenance_counts(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset, corpus = _write_inputs(
                directory,
                provenance="anonymized_real_user_question",
            )
            first = json.loads(dataset.read_text(encoding="utf-8"))
            second = dict(first)
            second.update(
                {
                    "case_id": "human-2",
                    "question": "What is not covered?",
                    "category": "no_answer",
                    "question_provenance": "human_task_without_corpus_view",
                    "should_abstain": True,
                    "unanswerable_reason": "outside the corpus",
                    "relevance_spans": [],
                }
            )
            dataset.write_text(
                json.dumps(first) + "\n" + json.dumps(second) + "\n",
                encoding="utf-8",
            )
            results = directory / "report.json"
            checksum = directory / "report.sha256"

            completed = _run(dataset, corpus, results, checksum)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(results.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["question_provenance_counts"],
                {
                    "anonymized_real_user_question": 1,
                    "human_task_without_corpus_view": 1,
                },
            )
            self.assertNotIn("provenance", payload)
    def test_prepares_checksum_before_report(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            results = directory / "report.json"
            checksum = directory / "report.sha256"
            report_bytes = b'{"status":"complete"}\n'
            digest_bytes = hashlib.sha256(report_bytes).hexdigest().encode("ascii") + b"\n"

            with mock.patch.object(
                report_cli,
                "_stage_bytes",
                wraps=report_cli._stage_bytes,
            ) as staged:
                report_cli._publish_artifacts(
                    results,
                    report_bytes,
                    checksum,
                    digest_bytes,
                )

            self.assertEqual(
                [call.args[0] for call in staged.call_args_list],
                [checksum, results],
            )
            self.assertEqual(results.read_bytes(), report_bytes)
            self.assertEqual(checksum.read_bytes(), digest_bytes)

    def test_path_recovery_matches_non_abbreviated_parser_and_separator(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                report_cli._build_parser().parse_args(["--res", "not-an-option"])

        abbreviated = report_cli._recover_path_args(["--res", "not-an-option"])
        separated = report_cli._recover_path_args(
            ["--", "--results", "not-an-option"]
        )

        self.assertEqual(abbreviated.results, report_cli.RESULTS)
        self.assertEqual(separated.results, report_cli.RESULTS)
    def test_help_after_separator_invalidates_stale_outputs(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset, corpus = _write_inputs(directory)
            results = directory / "report.json"
            checksum = directory / "report.sha256"
            results.write_text("STALE_REPORT", encoding="utf-8")
            checksum.write_text("STALE_CHECKSUM", encoding="utf-8")

            completed = subprocess.run(
                [
                    str(PYTHON), str(SCRIPT),
                    "--dataset", str(dataset),
                    "--corpus", str(corpus),
                    "--results", str(results),
                    "--checksum", str(checksum),
                    "--", "--help",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(results.exists())
            self.assertFalse(checksum.exists())
            self.assertTrue(dataset.exists())
            self.assertTrue(corpus.exists())


if __name__ == "__main__":
    unittest.main()
