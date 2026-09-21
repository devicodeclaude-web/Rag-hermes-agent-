import unittest

from rag_hermes.local_hardening import (
    build_local_workload_command,
    build_local_user_bootstrap,
)


class LocalHardeningTests(unittest.TestCase):
    def test_bootstrap_creates_non_root_user_and_owned_dir(self):
        script = build_local_user_bootstrap("hermesrag", "/opt/hermesrag")
        self.assertIn("useradd", script)
        self.assertIn("hermesrag", script)
        self.assertIn("/opt/hermesrag", script)
        self.assertNotIn("rm -rf", script)

    def test_root_is_rejected_as_local_user(self):
        with self.assertRaises(ValueError):
            build_local_user_bootstrap("root", "/opt/x")

    def test_workload_runs_under_non_root_user(self):
        command = build_local_workload_command(
            "hermesrag", "python -m unittest discover -s tests"
        )
        self.assertIn("runuser -u hermesrag", command)
        self.assertIn("python -m unittest", command)

    def test_workload_rejects_empty_command(self):
        with self.assertRaises(ValueError):
            build_local_workload_command("hermesrag", "   ")

    def test_relative_workspace_is_rejected(self):
        with self.assertRaises(ValueError):
            build_local_user_bootstrap("hermesrag", "relative/path")


if __name__ == "__main__":
    unittest.main()
