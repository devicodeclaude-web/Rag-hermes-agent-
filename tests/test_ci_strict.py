import io
import os
import unittest
from unittest.mock import patch

import scripts.run_ci_strict as run_ci_strict


class StrictCiSecretScannerTests(unittest.TestCase):
    def test_missing_gitleaks_is_a_hard_failure(self):
        stderr = io.StringIO()
        with (
            patch.object(run_ci_strict.shutil, "which", return_value=None),
            patch.object(run_ci_strict.os.path, "exists", return_value=False),
            patch.dict(run_ci_strict.os.environ, {}, clear=False),
            patch.object(run_ci_strict.sys, "stderr", stderr),
        ):
            run_ci_strict.os.environ.pop(run_ci_strict.GITLEAKS_BIN_ENV, None)
            result = run_ci_strict.run_gitleaks()

        self.assertNotEqual(result, 0)
        self.assertIn("ECHEC CI", stderr.getvalue())
        self.assertIn("gitleaks absent", stderr.getvalue())

    def test_world_writable_tmp_binary_is_never_a_fallback(self):
        """Un /tmp/gitleaks posé par n'importe quel processus local ne doit JAMAIS
        être exécuté implicitement : sans PATH ni GITLEAKS_BIN, c'est un échec dur."""
        stderr = io.StringIO()
        with (
            patch.object(run_ci_strict.shutil, "which", return_value=None),
            # Le chemin /tmp/gitleaks EXISTE : l'ancien repli l'aurait exécuté.
            patch.object(run_ci_strict.os.path, "exists", return_value=True),
            patch.object(run_ci_strict.os.path, "isfile", return_value=True),
            patch.object(run_ci_strict.os, "access", return_value=True),
            patch.dict(run_ci_strict.os.environ, {}, clear=False),
            patch.object(run_ci_strict.subprocess, "run") as runner,
            patch.object(run_ci_strict.sys, "stderr", stderr),
        ):
            run_ci_strict.os.environ.pop(run_ci_strict.GITLEAKS_BIN_ENV, None)
            result = run_ci_strict.run_gitleaks()

        self.assertNotEqual(result, 0)
        runner.assert_not_called()
        self.assertIn("ECHEC CI", stderr.getvalue())

    def test_explicit_gitleaks_bin_is_used(self):
        """Le scanner doit venir d'un chemin explicite (GITLEAKS_BIN) ou du PATH."""
        explicit = "/opt/scanners/gitleaks"

        class _Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        with (
            patch.object(run_ci_strict.shutil, "which", return_value=None),
            patch.object(run_ci_strict.os.path, "isfile", return_value=True),
            patch.object(run_ci_strict.os, "access", return_value=True),
            patch.dict(
                run_ci_strict.os.environ,
                {run_ci_strict.GITLEAKS_BIN_ENV: explicit},
                clear=False,
            ),
            patch.object(
                run_ci_strict.subprocess, "run", return_value=_Completed()
            ) as runner,
        ):
            result = run_ci_strict.run_gitleaks()

        self.assertEqual(result, 0)
        runner.assert_called_once()
        self.assertEqual(runner.call_args[0][0][0], explicit)

    def test_unusable_explicit_gitleaks_bin_is_a_hard_failure(self):
        """Un GITLEAKS_BIN qui ne pointe pas sur un exécutable ne se rabat sur rien."""
        stderr = io.StringIO()
        with (
            patch.object(run_ci_strict.shutil, "which", return_value="/usr/bin/gitleaks"),
            patch.object(run_ci_strict.os.path, "isfile", return_value=False),
            patch.dict(
                run_ci_strict.os.environ,
                {run_ci_strict.GITLEAKS_BIN_ENV: "/nope/gitleaks"},
                clear=False,
            ),
            patch.object(run_ci_strict.subprocess, "run") as runner,
            patch.object(run_ci_strict.sys, "stderr", stderr),
        ):
            result = run_ci_strict.run_gitleaks()

        self.assertNotEqual(result, 0)
        runner.assert_not_called()
        self.assertIn("ECHEC CI", stderr.getvalue())


class StrictCiWorkflowCoverageTests(unittest.TestCase):
    """La suite stricte doit être un contrôle de PR universel (constat CI-01 des
    audits externes du 18/11/2026) : sans trigger `pull_request` et sans filtre
    de chemins, une PR touchant `rag_hermes/**` ne déclenchait aucun test."""

    WORKFLOW = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".github",
        "workflows",
        "lock-install-x86_64-py312.yml",
    )

    def _trigger_block(self) -> str:
        with open(self.WORKFLOW, encoding="utf-8") as handle:
            text = handle.read()
        start = text.index("\non:\n")
        end = text.index("\npermissions:")
        return text[start:end]

    def test_strict_suite_runs_on_pull_requests(self):
        self.assertIn("pull_request:", self._trigger_block())

    def test_strict_suite_runs_on_main_pushes(self):
        block = self._trigger_block()
        self.assertIn("push:", block)
        self.assertIn("branches: [main]", block)

    def test_triggers_carry_no_path_filters(self):
        """Un filtre `paths` laisserait des modifications de code hors CI."""
        self.assertNotIn("paths:", self._trigger_block())

    def test_every_action_is_pinned_to_a_commit_sha(self):
        """Les actions épinglées par tag mobile (SUP-01) sont refusées."""
        workflows_dir = os.path.dirname(self.WORKFLOW)
        offenders = []
        for name in sorted(os.listdir(workflows_dir)):
            if not name.endswith((".yml", ".yaml")):
                continue
            path = os.path.join(workflows_dir, name)
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, start=1):
                    stripped = line.strip()
                    if "uses:" not in stripped or stripped.startswith("#"):
                        continue
                    reference = stripped.split("uses:", 1)[1].strip()
                    if "@" not in reference:
                        offenders.append(f"{name}:{number}: {reference}")
                        continue
                    pinned = reference.rsplit("@", 1)[1].split()[0]
                    if len(pinned) != 40 or any(
                        character not in "0123456789abcdef" for character in pinned
                    ):
                        offenders.append(f"{name}:{number}: {reference}")
        self.assertEqual(offenders, [], f"actions non épinglées par SHA : {offenders}")


class AuditLockCompletenessTests(unittest.TestCase):
    """`requirements-audit.lock.txt` doit suffire à faire passer la suite sur un
    clone neuf : `numpy` manquait alors que des tests l'importent."""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_audit_lock_covers_every_third_party_test_import(self):
        with open(
            os.path.join(self.ROOT, "requirements-audit.lock.txt"), encoding="utf-8"
        ) as handle:
            lock = handle.read()
        pinned = {
            line.split("==", 1)[0].strip().lower()
            for line in lock.splitlines()
            if "==" in line and not line.startswith(" ")
        }
        for distribution in ("hypothesis", "numpy"):
            self.assertIn(distribution, pinned)

    def test_audit_lock_pins_hashes_for_every_distribution(self):
        with open(
            os.path.join(self.ROOT, "requirements-audit.lock.txt"), encoding="utf-8"
        ) as handle:
            lines = [line.rstrip("\n") for line in handle if line.strip()]
        current = None
        hashes: dict[str, int] = {}
        for line in lines:
            if not line.startswith(" ") and "==" in line:
                current = line.split("==", 1)[0].strip().lower()
                hashes.setdefault(current, 0)
            elif "--hash=sha256:" in line and current is not None:
                hashes[current] += 1
        self.assertTrue(hashes)
        for distribution, count in hashes.items():
            self.assertGreater(count, 0, f"{distribution} sans hash")


if __name__ == "__main__":
    unittest.main()
