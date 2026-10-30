from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rag_hermes.execution_receipt import (
    load_consumable_receipt_v2,
    run_with_receipt,
    validate_consumable_receipt_v2,
)


class ExecutionReceiptTests(unittest.TestCase):
    def _completed_receipt(self, report=None) -> dict[str, object]:
        if report is None:
            report = {"nested": {"value": 3}, "ok": True}
        canonical = json.dumps(
            report, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return {
            "schema_version": "gpu_execution_receipt.v2",
            "status": "completed",
            "started_utc": "2026-10-18T11:00:00Z",
            "finished_utc": "2026-10-18T11:01:00Z",
            "command": [sys.executable, "scripts/run_bge_gpu_smoke.py"],
            "cwd": "/tmp/rag-hermes-agent",
            "environment": {"PYTHONHASHSEED": "1542026"},
            "exit_code": 0,
            "report": report,
            "report_encoding": "canonical-json-utf8",
            "report_sha256_scope": "receipt.report canonical-json-utf8",
            "report_sha256": hashlib.sha256(canonical).hexdigest(),
        }

    def test_load_consumable_receipt_v2_accepts_valid_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            expected = self._completed_receipt()
            path.write_text(json.dumps(expected), encoding="utf-8")

            self.assertEqual(load_consumable_receipt_v2(path), expected)

    def test_consumable_receipt_requires_all_autonomous_fields(self) -> None:
        autonomous_fields = (
            "command",
            "cwd",
            "environment",
            "started_utc",
            "finished_utc",
        )
        for field in autonomous_fields:
            with self.subTest(field=field):
                receipt = self._completed_receipt()
                del receipt[field]

                with self.assertRaisesRegex(ValueError, "keys"):
                    validate_consumable_receipt_v2(receipt)

    def test_consumable_receipt_rejects_unknown_keys(self) -> None:
        receipt = self._completed_receipt()
        receipt["unexpected"] = "not part of v2"

        with self.assertRaisesRegex(ValueError, "keys"):
            validate_consumable_receipt_v2(receipt)

    def test_consumable_receipt_validates_autonomous_field_types_and_constraints(self) -> None:
        invalid_fields = (
            ("command", [], "command"),
            ("command", [sys.executable, ""], "command"),
            ("command", [sys.executable, 3], "command"),
            ("cwd", "relative/path", "cwd"),
            ("cwd", 3, "cwd"),
            ("environment", [], "environment"),
            ("environment", {3: "value"}, "environment"),
            ("environment", {"KEY": 3}, "environment"),
            ("started_utc", "not-a-timestamp", "started_utc"),
            ("started_utc", "2026-10-18T11:00:00+01:00", "started_utc"),
            ("finished_utc", 3, "finished_utc"),
            ("finished_utc", "2026-10-18T10:59:59Z", "finished_utc"),
        )
        for field, value, error in invalid_fields:
            with self.subTest(field=field, value=value):
                receipt = self._completed_receipt()
                receipt[field] = value

                with self.assertRaisesRegex(ValueError, error):
                    validate_consumable_receipt_v2(receipt)

    def test_consumable_receipt_rejects_nonfinite_constants_anywhere_in_envelope(self) -> None:
        mutations = (
            lambda receipt, value: receipt.__setitem__("status", value),
            lambda receipt, value: receipt["command"].append(value),
            lambda receipt, value: receipt["environment"].__setitem__("BAD", value),
            lambda receipt, value: receipt["report"].__setitem__("value", value),
        )
        for value in (float("nan"), float("inf"), float("-inf")):
            for mutate in mutations:
                with self.subTest(value=value, location=mutations.index(mutate)):
                    receipt = self._completed_receipt()
                    mutate(receipt, value)

                    with self.assertRaisesRegex(ValueError, "strict JSON"):
                        validate_consumable_receipt_v2(receipt)

    def test_consumable_receipt_requires_exact_v2_schema_version(self) -> None:
        for version in (None, "gpu_execution_receipt.v1"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "receipt.json"
                receipt = self._completed_receipt()
                if version is None:
                    del receipt["schema_version"]
                else:
                    receipt["schema_version"] = version
                path.write_text(json.dumps(receipt), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "schema_version"):
                    load_consumable_receipt_v2(path)

    def test_consumable_receipt_requires_completed_zero_exit_object_report(self) -> None:
        invalid_fields = (
            ("status", "failed"),
            ("exit_code", 1),
            ("report", []),
        )
        for field, value in invalid_fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "receipt.json"
                receipt = self._completed_receipt()
                receipt[field] = value
                path.write_text(json.dumps(receipt), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, field):
                    load_consumable_receipt_v2(path)

    def test_consumable_receipt_requires_exact_encoding_and_hash_scope(self) -> None:
        invalid_fields = (
            ("report_encoding", "json-utf8"),
            ("report_sha256_scope", "staging file bytes"),
        )
        for field, value in invalid_fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "receipt.json"
                receipt = self._completed_receipt()
                receipt[field] = value
                path.write_text(json.dumps(receipt), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, field):
                    load_consumable_receipt_v2(path)

    def test_consumable_receipt_rejects_malformed_and_mismatched_hashes(self) -> None:
        for digest, error in (("not-a-hash", "64"), ("0" * 64, "mismatch")):
            with self.subTest(digest=digest), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "receipt.json"
                receipt = self._completed_receipt()
                receipt["report_sha256"] = digest
                path.write_text(json.dumps(receipt), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, error):
                    load_consumable_receipt_v2(path)

    def test_consumable_receipt_rejects_nonstandard_numeric_report_values(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                receipt = self._completed_receipt()
                receipt["report"] = {"value": value}

                with self.assertRaisesRegex(ValueError, "strict JSON"):
                    validate_consumable_receipt_v2(receipt)

    def test_success_publishes_autonomous_completed_receipt_and_removes_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            report = results / "report.json"
            receipt = results / "receipt.json"
            child = root / "child.py"
            child.write_text(
                "import os, pathlib\n"
                "pathlib.Path(os.environ['REPORT']).write_text('{\"nested\":{\"value\":3},\"ok\":true}\\n')\n",
                encoding="utf-8",
            )
            command = [sys.executable, str(child)]
            env = {"REPORT": str(report), "CAMPAIGN": "human-154"}

            exit_code = run_with_receipt(
                command,
                cwd=root,
                environment=env,
                report_path=report,
                receipt_path=receipt,
                approved_results_directory=results,
            )

            proof = json.loads(receipt.read_text(encoding="utf-8"))
            expected_report = {"nested": {"value": 3}, "ok": True}
            canonical_report = json.dumps(
                expected_report, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            self.assertEqual(exit_code, 0)
            self.assertEqual(proof["command"], command)
            self.assertEqual(proof["environment"], env)
            self.assertEqual(proof["exit_code"], 0)
            self.assertEqual(proof["status"], "completed")
            self.assertEqual(proof["report"], expected_report)
            self.assertEqual(
                proof["report_sha256"], hashlib.sha256(canonical_report).hexdigest()
            )
            self.assertEqual(proof["report_encoding"], "canonical-json-utf8")
            self.assertEqual(
                proof["report_sha256_scope"], "receipt.report canonical-json-utf8"
            )
            self.assertFalse(report.exists())

    def test_protected_input_aliases_are_rejected_before_any_removal(self) -> None:
        for artifact in ("report", "receipt"):
            for alias_kind in ("identical", "resolved"):
                with self.subTest(artifact=artifact, alias_kind=alias_kind), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    results = root / "results"
                    results.mkdir()
                    protected = results / "protected.json"
                    protected.write_text("PROTECTED\n", encoding="utf-8")
                    alias = (
                        protected
                        if alias_kind == "identical"
                        else results / ".." / "results" / "protected.json"
                    )
                    report = alias if artifact == "report" else results / "report.json"
                    receipt = alias if artifact == "receipt" else results / "receipt.json"

                    with self.assertRaisesRegex(ValueError, "protected input"):
                        run_with_receipt(
                            [sys.executable, "-c", "raise SystemExit(9)"],
                            cwd=root,
                            environment={},
                            report_path=report,
                            receipt_path=receipt,
                            approved_results_directory=results,
                            protected_paths=[protected],
                        )

                    self.assertEqual(protected.read_text(encoding="utf-8"), "PROTECTED\n")
                    self.assertFalse((results / "report.json").exists())
                    self.assertFalse((results / "receipt.json").exists())

    def test_protected_input_hardlinks_are_rejected_before_any_removal(self) -> None:
        import os

        for artifact in ("report", "receipt"):
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                results = root / "results"
                results.mkdir()
                protected = root / "protected.json"
                protected.write_text("PROTECTED\n", encoding="utf-8")
                alias = results / f"{artifact}.json"
                subprocess.run(["ln", str(protected), str(alias)], check=True)
                report = alias if artifact == "report" else results / "report.json"
                receipt = alias if artifact == "receipt" else results / "receipt.json"

                with self.assertRaisesRegex(ValueError, "protected input"):
                    run_with_receipt(
                        [sys.executable, "-c", "raise SystemExit(9)"],
                        cwd=root,
                        environment={},
                        report_path=report,
                        receipt_path=receipt,
                        approved_results_directory=results,
                        protected_paths=[protected],
                    )

                self.assertEqual(protected.read_text(encoding="utf-8"), "PROTECTED\n")
                self.assertTrue(alias.exists())
                self.assertTrue(os.path.samefile(protected, alias))

    def test_failure_leaves_no_consumable_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            report = results / "report.json"
            receipt = results / "receipt.json"
            report.write_text('{"stale":true}\n', encoding="utf-8")
            receipt.write_text(
                '{"status":"completed","report":{"stale":true}}\n',
                encoding="utf-8",
            )
            child = root / "fail.py"
            child.write_text("raise SystemExit(7)\n", encoding="utf-8")

            exit_code = run_with_receipt(
                [sys.executable, str(child)],
                cwd=root,
                environment={},
                report_path=report,
                receipt_path=receipt,
                approved_results_directory=results,
            )

            proof = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 7)
            self.assertFalse(report.exists())
            self.assertEqual(proof["exit_code"], 7)
            self.assertEqual(proof["status"], "failed")
            self.assertIsNone(proof["report"])
            self.assertIsNone(proof["report_encoding"])
            self.assertIsNone(proof["report_sha256"])

    def test_invalid_staging_json_leaves_no_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            report = results / "report.json"
            receipt = results / "receipt.json"
            child = root / "invalid.py"
            child.write_text(
                "import os, pathlib\n"
                "pathlib.Path(os.environ['REPORT']).write_text('not-json')\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "invalid JSON report"):
                run_with_receipt(
                    [sys.executable, str(child)],
                    cwd=root,
                    environment={"REPORT": str(report)},
                    report_path=report,
                    receipt_path=receipt,
                    approved_results_directory=results,
                )

            self.assertFalse(report.exists())
            self.assertFalse(receipt.exists())

    def test_nonstandard_numeric_staging_json_leaves_no_artifact(self) -> None:
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                results = root / "results"
                results.mkdir()
                report = results / "report.json"
                receipt = results / "receipt.json"
                receipt.write_text(
                    '{"schema_version":"gpu_execution_receipt.v2","status":"completed"}\n',
                    encoding="utf-8",
                )
                child = root / "nonstandard.py"
                child.write_text(
                    "import os, pathlib\n"
                    f"pathlib.Path(os.environ['REPORT']).write_text('{{\"value\":{constant}}}')\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(RuntimeError, "invalid JSON report"):
                    run_with_receipt(
                        [sys.executable, str(child)],
                        cwd=root,
                        environment={"REPORT": str(report)},
                        report_path=report,
                        receipt_path=receipt,
                        approved_results_directory=results,
                    )

                self.assertFalse(report.exists())
                self.assertFalse(receipt.exists())

    def test_receipt_publication_failure_removes_success_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            report = results / "report.json"
            receipt = results / "receipt.json"
            child = root / "child.py"
            child.write_text(
                "import os, pathlib\n"
                "pathlib.Path(os.environ['REPORT']).write_text('{\"new\":true}\\n')\n",
                encoding="utf-8",
            )
            with patch(
                "rag_hermes.execution_receipt._write_json_atomic",
                side_effect=OSError("publish failed"),
            ):
                with self.assertRaisesRegex(OSError, "publish failed"):
                    run_with_receipt(
                        [sys.executable, str(child)],
                        cwd=root,
                        environment={"REPORT": str(report)},
                        report_path=report,
                        receipt_path=receipt,
                        approved_results_directory=results,
                    )
            self.assertFalse(report.exists())
            self.assertFalse(receipt.exists())

    def test_report_substitution_after_read_cannot_change_embedded_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            report = results / "report.json"
            receipt = results / "receipt.json"
            replacement = results / "replacement.json"
            replacement.write_text('{"source":"replacement"}\n', encoding="utf-8")
            child = root / "child.py"
            child.write_text(
                "import os, pathlib\n"
                "pathlib.Path(os.environ['REPORT']).write_text('{\"source\":\"original\"}\\n')\n",
                encoding="utf-8",
            )

            from rag_hermes import execution_receipt as receipt_module

            original_publish = receipt_module._write_json_atomic

            def substitute_then_publish(results_fd, name, payload):
                os.replace(
                    "replacement.json",
                    "report.json",
                    src_dir_fd=results_fd,
                    dst_dir_fd=results_fd,
                )
                original_publish(results_fd, name, payload)

            import os

            with patch(
                "rag_hermes.execution_receipt._write_json_atomic",
                side_effect=substitute_then_publish,
            ):
                exit_code = run_with_receipt(
                    [sys.executable, str(child)],
                    cwd=root,
                    environment={"REPORT": str(report)},
                    report_path=report,
                    receipt_path=receipt,
                    approved_results_directory=results,
                )

            proof = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(proof["report"], {"source": "original"})
            self.assertFalse(report.exists())
            self.assertFalse(replacement.exists())

    def test_receipt_hash_and_publication_are_descriptor_anchored(self) -> None:
        source = Path("rag_hermes/execution_receipt.py").read_text(encoding="utf-8")

        self.assertIn("os.O_NOFOLLOW", source)
        self.assertIn("os.fstat(report_fd)", source)
        self.assertIn("_read_fd_bytes(report_fd)", source)
        self.assertIn("_canonical_json_bytes(report_payload)", source)
        self.assertIn("dir_fd=results_fd", source)
        self.assertIn("src_dir_fd=results_fd", source)
        self.assertIn("dst_dir_fd=results_fd", source)
        self.assertIn("os.fsync(results_fd)", source)
        self.assertNotIn("_sha256(report_path)", source)
        self.assertNotIn("temporary.replace(path)", source)

    def test_receipt_stays_anchored_if_results_path_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            moved_results = root / "results-moved"
            outside = root / "outside"
            outside.mkdir()
            report = results / "report.json"
            receipt = results / "receipt.json"
            child = root / "swap_parent.py"
            child.write_text(
                "import os, pathlib\n"
                "results = pathlib.Path(os.environ['RESULTS'])\n"
                "moved = pathlib.Path(os.environ['MOVED'])\n"
                "outside = pathlib.Path(os.environ['OUTSIDE'])\n"
                "(results / 'report.json').write_text('{\"source\":\"original\"}\\n')\n"
                "results.rename(moved)\n"
                "results.symlink_to(outside, target_is_directory=True)\n"
                "(outside / 'report.json').write_text('{\"source\":\"fake\"}\\n')\n",
                encoding="utf-8",
            )

            exit_code = run_with_receipt(
                [sys.executable, str(child)],
                cwd=root,
                environment={
                    "RESULTS": str(results),
                    "MOVED": str(moved_results),
                    "OUTSIDE": str(outside),
                },
                report_path=report,
                receipt_path=receipt,
                approved_results_directory=results,
            )

            proof = json.loads((moved_results / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(
                proof["report"], {"source": "original"}
            )
            self.assertFalse((moved_results / "report.json").exists())
            self.assertFalse((outside / "receipt.json").exists())
            self.assertEqual(
                json.loads((outside / "report.json").read_text()), {"source": "fake"}
            )

    def test_zero_exit_symlink_report_is_removed_before_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            report = results / "report.json"
            receipt = results / "receipt.json"
            target = root / "outside.json"
            target.write_text("DO NOT DELETE\n", encoding="utf-8")
            child = root / "symlink_report.py"
            child.write_text(
                "import os, pathlib\n"
                "pathlib.Path(os.environ['REPORT']).symlink_to(os.environ['TARGET'])\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "regular report artifact"):
                run_with_receipt(
                    [sys.executable, str(child)],
                    cwd=root,
                    environment={"REPORT": str(report), "TARGET": str(target)},
                    report_path=report,
                    receipt_path=receipt,
                    approved_results_directory=results,
                )

            self.assertFalse(report.exists())
            self.assertFalse(report.is_symlink())
            self.assertEqual(target.read_text(encoding="utf-8"), "DO NOT DELETE\n")
            self.assertFalse(receipt.exists())

    def test_zero_exit_directory_report_is_removed_before_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            report = results / "report.json"
            receipt = results / "receipt.json"
            child = root / "directory_report.py"
            child.write_text(
                "import os, pathlib\n"
                "report = pathlib.Path(os.environ['REPORT'])\n"
                "report.mkdir()\n"
                "(report / 'partial.json').write_text('PARTIAL\\n')\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "regular report artifact"):
                run_with_receipt(
                    [sys.executable, str(child)],
                    cwd=root,
                    environment={"REPORT": str(report)},
                    report_path=report,
                    receipt_path=receipt,
                    approved_results_directory=results,
                )

            self.assertFalse(report.exists())
            self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
