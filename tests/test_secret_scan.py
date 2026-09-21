import unittest

from rag_hermes.secret_scan import scan_text


class SecretScanTests(unittest.TestCase):
    def test_detects_private_ssh_key_header(self):
        findings = scan_text("x.pem", "-----BEGIN OPENSSH PRIVATE KEY-----")
        self.assertTrue(any(f.rule == "private_key" for f in findings))

    def test_detects_assigned_api_key(self):
        findings = scan_text("cfg.py", 'api_key = "sk-abcdef1234567890abcdef"')
        self.assertTrue(any(f.rule == "assigned_secret" for f in findings))

    def test_ignores_placeholder_and_env_reference(self):
        findings = scan_text("cfg.py", 'api_key = os.environ["RUNPOD_API_KEY"]')
        self.assertEqual(findings, [])

    def test_ignores_short_values(self):
        findings = scan_text("cfg.py", 'token = "abc"')
        self.assertEqual(findings, [])

    def test_reports_line_number(self):
        text = "ok = 1\npassword = \"supersecretvalue123\"\n"
        findings = scan_text("cfg.py", text)
        self.assertEqual(findings[0].line, 2)


if __name__ == "__main__":
    unittest.main()
