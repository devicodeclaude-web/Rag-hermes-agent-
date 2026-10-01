from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time
import unittest
from urllib import request as urllib_request

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

    def test_real_server_import_question_citation_and_clean_sigterm(self) -> None:
        """Exercise the actual serve_v1 process over a real TCP socket."""
        env = os.environ.copy()
        for name in tuple(env):
            if name.startswith("RAG_GENERATOR_") or name.startswith("RAG_QDRANT_"):
                env.pop(name)

        process = subprocess.Popen(
            [sys.executable, "scripts/serve_v1.py", "--port", "0"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        startup = ""
        try:
            assert process.stdout is not None
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    startup += process.stdout.readline()
                    if "http://" in startup:
                        break

            match = re.search(r"http://127\.0\.0\.1:(\d+)", startup)
            if match is None:
                stdout_tail, stderr = process.communicate(timeout=2)
                startup += stdout_tail
                self.fail(
                    f"server did not publish an ephemeral port; stdout={startup!r} "
                    f"stderr={stderr!r} rc={process.returncode}"
                )
            port = int(match.group(1))
            self.assertGreater(port, 0)

            context = {
                "tenant_id": "network-test",
                "user_id": "alice",
                "groups": ["owners"],
                "clearance": 1,
            }

            def post(path: str, payload: dict) -> tuple[int, dict, dict]:
                body = json.dumps(payload).encode("utf-8")
                req = urllib_request.Request(
                    f"http://127.0.0.1:{port}{path}",
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib_request.urlopen(req, timeout=5) as response:
                    return (
                        response.status,
                        dict(response.headers),
                        json.loads(response.read().decode("utf-8")),
                    )

            status, headers, imported = post(
                "/api/documents",
                {
                    "context": context,
                    "document": {
                        "document_id": "network-guide",
                        "content": "Hermes starts the local agent with the hermes command.",
                        "tenant_id": "network-test",
                        "visibility": "private",
                        "owner_id": "alice",
                        "allowed_groups": ["owners"],
                        "allowed_users": [],
                        "classification": 1,
                        "doc_version": 1,
                        "source_uri": "local://network-guide",
                    },
                },
            )
            self.assertEqual(status, 201)
            self.assertGreater(imported["chunk_count"], 0)
            self.assertEqual(headers["X-Frame-Options"], "DENY")

            status, headers, answer = post(
                "/api/questions",
                {"context": context, "question": "How does Hermes start the local agent?"},
            )
            self.assertEqual(status, 200)
            self.assertFalse(answer["abstained"])
            self.assertEqual(answer["citations"][0]["document_id"], "network-guide")
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=8)
            startup += stdout
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn("Arrêt du serveur.", startup)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
