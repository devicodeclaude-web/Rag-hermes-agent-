import unittest
from types import SimpleNamespace

from rag_hermes.integration_gate import assert_no_skipped_integration_tests


class IntegrationGateTests(unittest.TestCase):
    def test_skip_is_a_hard_failure(self):
        result = SimpleNamespace(
            testsRun=1,
            skipped=[("qdrant-test", "Qdrant integration disabled")],
            failures=[],
            errors=[],
        )
        with self.assertRaisesRegex(RuntimeError, "skipped"):
            assert_no_skipped_integration_tests(result, expected_tests=1)


if __name__ == "__main__":
    unittest.main()
