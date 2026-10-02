from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import scripts.compare_campaigns as compare_cli

ROOT = Path(__file__).resolve().parents[1]


class _FailingProvider(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self) -> None:
        type(self).calls += 1
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"provider unavailable"}')

    def log_message(self, format: str, *args: object) -> None:
        pass


class CompareCampaignsCliTests(unittest.TestCase):
    def test_second_unlink_failure_leaves_no_consumable_stale_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "comparison.json"
            review = root / "review.jsonl"
            report.write_text("STALE_REPORT\n", encoding="utf-8")
            review.write_text("STALE_REVIEW\n", encoding="utf-8")
            real_unlink = Path.unlink

            def fail_review_unlink(path: Path, missing_ok: bool = False) -> None:
                if path == review:
                    raise OSError("injected unlink failure")
                real_unlink(path, missing_ok=missing_ok)

            with patch.object(Path, "unlink", new=fail_review_unlink):
                with self.assertRaises(OSError):
                    compare_cli._invalidate_outputs((report, review))

            self.assertFalse(report.exists())
            self.assertTrue(review.exists())
            self.assertEqual(
                review.read_text(encoding="utf-8"),
                '{"status":"INVALIDATED"}\n',
            )

    def test_report_is_commit_marker_when_second_publish_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "comparison.json"
            review = root / "review.jsonl"
            real_replace = os.replace
            calls = 0

            def fail_report_replace(
                source: str | os.PathLike[str],
                destination: str | os.PathLike[str],
            ) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected report publication failure")
                real_replace(source, destination)

            with patch.object(os, "replace", new=fail_report_replace):
                with self.assertRaises(OSError):
                    compare_cli._publish_artifacts(
                        report,
                        '{"status":"complete"}\n',
                        review,
                        '{"case_id":"q1"}\n',
                    )

            self.assertFalse(report.exists())
            self.assertTrue(review.exists())
            self.assertEqual(review.read_text(encoding="utf-8"), '{"case_id":"q1"}\n')
            self.assertEqual(
                list(root.glob(".*.tmp.*")),
                [],
            )

    def test_help_does_not_invalidate_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "comparison.json"
            review = root / "review.jsonl"
            report.write_text("CURRENT_REPORT\n", encoding="utf-8")
            review.write_text("CURRENT_REVIEW\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_campaigns.py",
                    "--report", str(report),
                    "--review", str(review),
                    "--help",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            self.assertEqual(completed.returncode, 0)
            self.assertEqual(report.read_text(encoding="utf-8"), "CURRENT_REPORT\n")
            self.assertEqual(review.read_text(encoding="utf-8"), "CURRENT_REVIEW\n")

    def test_invalid_arguments_invalidate_previous_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "comparison.json"
            review = root / "review.jsonl"
            report.write_text("STALE_REPORT\n", encoding="utf-8")
            review.write_text("STALE_REVIEW\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_campaigns.py",
                    "--report", str(report),
                    "--review", str(review),
                    "--seed", "not-an-int",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(report.exists())
            self.assertFalse(review.exists())

    def test_hardlink_output_alias_to_input_is_refused_without_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset.jsonl"
            corpus = root / "corpus.jsonl"
            report = root / "comparison.json"
            review = root / "review.jsonl"
            dataset.write_text("INPUT_DATASET\n", encoding="utf-8")
            corpus.write_text("INPUT_CORPUS\n", encoding="utf-8")
            subprocess.run(["ln", str(dataset), str(report)], check=True)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_campaigns.py",
                    "--dataset", str(dataset),
                    "--corpus", str(corpus),
                    "--report", str(report),
                    "--review", str(review),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertIn("output paths", completed.stderr)
            self.assertTrue(report.exists())
            self.assertEqual(dataset.read_text(encoding="utf-8"), "INPUT_DATASET\n")

    def test_baseline_http_failure_is_backend_error_not_abstention(self) -> None:
        _FailingProvider.calls = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FailingProvider)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                report = tmp_path / "comparison.json"
                review = tmp_path / "review.jsonl"
                dataset = tmp_path / "dataset.jsonl"
                corpus = tmp_path / "corpus.jsonl"
                dataset.write_text(
                    (ROOT / "data/benchmark/dataset-synthetic.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()[0]
                    + "\n",
                    encoding="utf-8",
                )
                corpus.write_text(
                    (ROOT / "data/generated/hermes_public_documents.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()[0]
                    + "\n",
                    encoding="utf-8",
                )
                report.write_text("STALE_REPORT\n", encoding="utf-8")
                review.write_text("STALE_REVIEW\n", encoding="utf-8")
                env = os.environ.copy()
                for key in tuple(env):
                    if key.startswith("RAG_GENERATOR_") or key.startswith("RAG_BASELINE_"):
                        env.pop(key)
                env.update(
                    {
                        "RAG_BASELINE_BASE_URL": (
                            f"http://127.0.0.1:{server.server_port}/v1"
                        ),
                        "RAG_BASELINE_MODEL": "failing-local-provider",
                    }
                )
                completed = subprocess.run(
                    [
                        sys.executable,
                        "scripts/compare_campaigns.py",
                        "--dataset", str(dataset),
                        "--corpus", str(corpus),
                        "--report", str(report),
                        "--review", str(review),
                    ],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )

                self.assertGreater(_FailingProvider.calls, 0)
                self.assertEqual(completed.returncode, 1, completed.stdout)
                self.assertIn("BACKEND_ERROR", completed.stderr)
                self.assertFalse(report.exists())
                self.assertFalse(review.exists())
                self.assertTrue(dataset.exists())
                self.assertTrue(corpus.exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
