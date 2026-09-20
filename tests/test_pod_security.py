import unittest

from rag_hermes.pod_security import build_non_root_bootstrap, run_as_user_command


class PodSecurityTests(unittest.TestCase):
    def test_bootstrap_creates_dedicated_user_and_owned_workspace(self):
        command = build_non_root_bootstrap("ragbench", "/opt/ragbench")
        self.assertIn("useradd", command)
        self.assertIn("ragbench", command)
        self.assertIn("/opt/ragbench", command)
        self.assertIn("chown", command)

    def test_root_is_forbidden_as_workload_user(self):
        with self.assertRaisesRegex(ValueError, "root"):
            build_non_root_bootstrap("root", "/opt/ragbench")

    def test_workload_command_drops_privileges(self):
        command = run_as_user_command("ragbench", "python scripts/run_bge_gpu_smoke.py")
        self.assertIn("runuser -u ragbench", command)
        self.assertIn("python scripts/run_bge_gpu_smoke.py", command)


if __name__ == "__main__":
    unittest.main()
