from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from scripts.runpod_serverless_handler import _run_in_process_group, run_campaign_job


REVISION = "a" * 40


def _receipt(revision: str = REVISION) -> dict[str, object]:
    report = {"code_revision": revision, "audited_commit": revision}
    report_bytes = json.dumps(
        report, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "gpu_execution_receipt.v2",
        "status": "completed",
        "started_utc": now,
        "finished_utc": now,
        "command": ["python", "campaign.py"],
        "cwd": "/opt/ragbench",
        "environment": {"RAG_CODE_REVISION": revision},
        "exit_code": 0,
        "report": report,
        "report_encoding": "canonical-json-utf8",
        "report_sha256_scope": "receipt.report canonical-json-utf8",
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
    }


class ServerlessHandlerTests(unittest.TestCase):
    def test_concurrent_campaign_is_rejected_before_second_runner_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "data/results").mkdir(parents=True)
            first_started = threading.Event()
            release_first = threading.Event()
            calls = []
            first_errors = []

            def runner(command, **kwargs):
                calls.append(command)
                if len(calls) == 1:
                    first_started.set()
                    release_first.wait(timeout=2)
                receipt_path = Path(command[command.index("--receipt") + 1])
                receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            def first_job():
                try:
                    run_campaign_job(
                        {"input": {"code_revision": REVISION}},
                        root=root,
                        runner=runner,
                        revision_validator=lambda value: str(value),
                    )
                except Exception as exc:
                    first_errors.append(exc)

            thread = threading.Thread(target=first_job)
            thread.start()
            self.assertTrue(first_started.wait(timeout=1))
            try:
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    run_campaign_job(
                        {"input": {"code_revision": REVISION}},
                        root=root,
                        runner=runner,
                        revision_validator=lambda value: str(value),
                    )
            finally:
                release_first.set()
                thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(first_errors, [])
            self.assertEqual(len(calls), 1)

    def test_timeout_kills_the_campaign_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "orphan-wrote-marker"
            child = root / "child.py"
            parent = root / "parent.py"
            child.write_text(
                "import pathlib,sys,time\n"
                "time.sleep(0.5)\n"
                "pathlib.Path(sys.argv[1]).write_text('orphan')\n",
                encoding="utf-8",
            )
            parent.write_text(
                "import subprocess,sys,time\n"
                "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n"
                "time.sleep(10)\n",
                encoding="utf-8",
            )
            with self.assertRaises(subprocess.TimeoutExpired):
                _run_in_process_group(
                    [sys.executable, str(parent), str(child), str(marker)],
                    cwd=root,
                    timeout=0.1,
                )
            time.sleep(0.7)
            self.assertFalse(marker.exists())

    def test_invalid_input_is_rejected_before_campaign_execution(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("runner must not execute")

        invalid_jobs = (
            {},
            {"input": None},
            {"input": {}},
            {"input": {"code_revision": REVISION, "unexpected": True}},
            {"input": {"code_revision": "ABC"}},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "data/results").mkdir(parents=True)
            for job in invalid_jobs:
                with self.subTest(job=job), self.assertRaises(ValueError):
                    run_campaign_job(
                        job,
                        root=root,
                        runner=runner,
                        revision_validator=lambda value: str(value),
                    )
        self.assertEqual(calls, [])

    def test_serverless_job_id_is_accepted_but_input_stays_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "data/results").mkdir(parents=True)

            def runner(command, **kwargs):
                receipt_path = Path(command[command.index("--receipt") + 1])
                receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            result = run_campaign_job(
                {"id": "job-123", "input": {"code_revision": REVISION}},
                root=root,
                runner=runner,
                revision_validator=lambda value: str(value),
            )
            self.assertEqual(result["report"]["code_revision"], REVISION)

    def test_valid_job_runs_audited_campaign_and_returns_validated_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "data/results").mkdir(parents=True)
            observed = {}

            def runner(command, **kwargs):
                observed["command"] = command
                observed["kwargs"] = kwargs
                receipt_path = Path(command[command.index("--receipt") + 1])
                receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            result = run_campaign_job(
                {"input": {"code_revision": REVISION}},
                root=root,
                runner=runner,
                revision_validator=lambda value: str(value),
            )

            self.assertEqual(result["schema_version"], "gpu_execution_receipt.v2")
            self.assertEqual(result["report"]["code_revision"], REVISION)
            self.assertEqual(observed["kwargs"]["cwd"], root)
            self.assertFalse(observed["kwargs"]["check"])
            self.assertEqual(
                observed["command"][1:3], ["-m", "scripts.run_bge_gpu_campaign"]
            )
            self.assertIn(REVISION, observed["command"])

    def test_timeout_removes_non_consumable_campaign_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            results = root / "data/results"
            results.mkdir(parents=True)
            staging = results / "bge_m3_human_154_report.json"
            receipt = results / "bge_m3_human_154_execution_receipt.json"

            def runner(command, **kwargs):
                staging.write_text("stale", encoding="utf-8")
                receipt.write_text(json.dumps(_receipt()), encoding="utf-8")
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])

            with self.assertRaisesRegex(RuntimeError, "time budget"):
                run_campaign_job(
                    {"input": {"code_revision": REVISION}},
                    root=root,
                    runner=runner,
                    revision_validator=lambda value: str(value),
                )
            self.assertFalse(staging.exists())
            self.assertFalse(receipt.exists())

    def test_unexpected_runner_failure_removes_non_consumable_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            results = root / "data/results"
            results.mkdir(parents=True)
            staging = results / "bge_m3_human_154_report.json"
            receipt = results / "bge_m3_human_154_execution_receipt.json"

            def runner(command, **kwargs):
                staging.write_text("stale", encoding="utf-8")
                receipt.write_text(json.dumps(_receipt()), encoding="utf-8")
                raise OSError("simulated spawn failure")

            with self.assertRaisesRegex(OSError, "simulated spawn failure"):
                run_campaign_job(
                    {"input": {"code_revision": REVISION}},
                    root=root,
                    runner=runner,
                    revision_validator=lambda value: str(value),
                )
            self.assertFalse(staging.exists())
            self.assertFalse(receipt.exists())

    def test_nonzero_campaign_exit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "data/results").mkdir(parents=True)

            staging = root / "data/results/bge_m3_human_154_report.json"
            receipt = root / "data/results/bge_m3_human_154_execution_receipt.json"

            def runner(command, **kwargs):
                staging.write_text("stale", encoding="utf-8")
                receipt.write_text(json.dumps(_receipt()), encoding="utf-8")
                return subprocess.CompletedProcess(command, 7)

            with self.assertRaisesRegex(RuntimeError, "campaign failed"):
                run_campaign_job(
                    {"input": {"code_revision": REVISION}},
                    root=root,
                    runner=runner,
                    revision_validator=lambda value: str(value),
                )
            self.assertFalse(staging.exists())
            self.assertFalse(receipt.exists())

    def test_receipt_revision_must_match_requested_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "data/results").mkdir(parents=True)

            receipt_path = root / "data/results/bge_m3_human_154_execution_receipt.json"

            def runner(command, **kwargs):
                receipt_path.write_text(json.dumps(_receipt("b" * 40)), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            with self.assertRaisesRegex(RuntimeError, "revision mismatch"):
                run_campaign_job(
                    {"input": {"code_revision": REVISION}},
                    root=root,
                    runner=runner,
                    revision_validator=lambda value: str(value),
                )
            self.assertFalse(receipt_path.exists())


if __name__ == "__main__":
    unittest.main()
