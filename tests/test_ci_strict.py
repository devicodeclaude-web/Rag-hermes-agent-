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


class StrictCiFixtureGateTests(unittest.TestCase):
    """Un test d'intégration ignoré fait échouer la CI : l'absence de fixture
    doit donc être nommée AVANT la suite, pas découverte via un `skip`."""

    def test_every_required_fixture_variable_is_reported_when_missing(self):
        with patch.dict(run_ci_strict.os.environ, {}, clear=True):
            self.assertEqual(
                run_ci_strict.missing_fixture_env(),
                list(run_ci_strict.REQUIRED_FIXTURE_ENV),
            )

    def test_blank_values_count_as_missing(self):
        blank = {name: "   " for name in run_ci_strict.REQUIRED_FIXTURE_ENV}
        with patch.dict(run_ci_strict.os.environ, blank, clear=True):
            self.assertEqual(
                run_ci_strict.missing_fixture_env(),
                list(run_ci_strict.REQUIRED_FIXTURE_ENV),
            )

    def test_auth_fixture_alone_missing_is_a_hard_failure_before_any_test(self):
        stderr = io.StringIO()
        partial = {"QDRANT_INTEGRATION_URL": "http://127.0.0.1:6333"}
        with (
            patch.dict(run_ci_strict.os.environ, partial, clear=True),
            patch.object(run_ci_strict, "run_gitleaks") as gitleaks,
            patch.object(run_ci_strict.unittest, "TestLoader") as loader,
            patch.object(run_ci_strict.sys, "stderr", stderr),
        ):
            code = run_ci_strict.main()
        self.assertEqual(code, 2)
        gitleaks.assert_not_called()
        loader.assert_not_called()
        self.assertIn("QDRANT_AUTH_INTEGRATION_URL", stderr.getvalue())
        self.assertIn("QDRANT_AUTH_ADMIN_KEY", stderr.getvalue())
        self.assertNotIn("QDRANT_INTEGRATION_URL,", stderr.getvalue())

    def test_the_workflow_supplies_every_required_fixture_variable(self):
        with open(StrictCiWorkflowCoverageTests.WORKFLOW, encoding="utf-8") as handle:
            workflow = handle.read()
        for name in run_ci_strict.REQUIRED_FIXTURE_ENV:
            self.assertIn(f"{name}:", workflow)


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


class SecretScanHistoryDepthTests(unittest.TestCase):
    """Le scan de secrets prétend couvrir l'historique : il doit le couvrir.

    `actions/checkout` sans `fetch-depth` ne récupère QU'UN commit, donc
    `gitleaks git` ne scannait qu'un commit tout en étant présenté comme un
    contrôle historique. Ces tests verrouillent la profondeur et le mode.
    """

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _workflow(self) -> dict:
        import yaml
        with open(StrictCiWorkflowCoverageTests.WORKFLOW, encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def test_checkout_fetches_the_whole_history(self):
        steps = self._workflow()["jobs"]["lock-install"]["steps"]
        checkouts = [
            step for step in steps
            if isinstance(step.get("uses"), str)
            and step["uses"].startswith("actions/checkout@")
        ]
        self.assertEqual(len(checkouts), 1)
        self.assertEqual(checkouts[0].get("with", {}).get("fetch-depth"), 0)

    def test_the_scanner_reads_git_history_not_just_the_working_tree(self):
        with open(
            os.path.join(self.ROOT, "scripts", "run_ci_strict.py"), encoding="utf-8"
        ) as handle:
            source = handle.read()
        self.assertIn('binary, "git"', source)
        self.assertNotIn('binary, "dir"', source)

    def test_allowlist_stays_an_exact_match_list_without_path_exclusions(self):
        import tomllib
        with open(os.path.join(self.ROOT, ".gitleaks.toml"), "rb") as handle:
            config = tomllib.load(handle)
        allowlists = config["allowlists"]
        self.assertTrue(allowlists)
        for entry in allowlists:
            self.assertEqual(entry.get("regexTarget"), "match")
            self.assertNotIn("paths", entry)
            self.assertNotIn("commits", entry)
            self.assertTrue(entry.get("regexes"))
            self.assertTrue(entry.get("description", "").strip())


class SecretScanEvidenceTests(unittest.TestCase):
    """La portée du scan doit être PROUVÉE par l'artefact, pas supposée.

    Sur succès, la sortie de gitleaks était capturée puis jetée : rien dans la
    preuve CI ne distinguait « 266 commits scannés » de « 1 commit scanné ».
    Et sur échec, les résultats bruts étaient recopiés dans le journal, ce qui
    y aurait écrit le secret trouvé.
    """

    class _Completed:
        def __init__(self, returncode=0):
            self.returncode = returncode
            self.stdout = ""
            self.stderr = "INF 266 commits scanned.\nINF no leaks found\n"

    def _run(self, returncode=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(run_ci_strict.shutil, "which", return_value="/usr/bin/gitleaks"),
            patch.dict(run_ci_strict.os.environ, {}, clear=True),
            patch.object(
                run_ci_strict.subprocess, "run",
                return_value=self._Completed(returncode),
            ) as runner,
            patch.object(run_ci_strict.sys, "stdout", stdout),
            patch.object(run_ci_strict.sys, "stderr", stderr),
        ):
            code = run_ci_strict.run_gitleaks()
        return code, stdout.getvalue(), stderr.getvalue(), runner

    def test_the_scanned_commit_count_is_recorded_on_success(self):
        code, out, _, _ = self._run()
        self.assertEqual(code, 0)
        self.assertIn("266 commits scanned", out)

    def test_findings_are_redacted_so_a_leak_never_reaches_the_log(self):
        _, _, _, runner = self._run()
        command = runner.call_args[0][0]
        self.assertIn("--redact", command)

    def test_a_failure_reports_the_summary_without_dumping_raw_findings(self):
        code, _, err, _ = self._run(returncode=1)
        self.assertNotEqual(code, 0)
        self.assertIn("ECHEC CI", err)
        self.assertIn("266 commits scanned", err)
