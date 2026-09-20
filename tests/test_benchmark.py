import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.benchmark import BenchmarkQuestion, run_lexical_benchmark
from rag_hermes.ingestion import Document


class BenchmarkTests(unittest.TestCase):
    def test_end_to_end_retrieval_respects_tenants_and_abstention(self):
        documents = [
            Document("public", "installer Hermes avec Termux", "public", "public", "docs", (), (), 0, 1, "git://docs/install.md"),
            Document("secret-a", "code interne ambre zephyr", "a", "private", "alice", ("admins",), (), 2, 1, "vault://a/secret.md"),
            Document("secret-b", "code interne cobalt orion", "b", "private", "bob", ("admins",), (), 2, 1, "vault://b/secret.md"),
        ]
        questions = [
            BenchmarkQuestion("q1", "Comment installer Hermes sous Termux ?", AuthorizationContext("a", "alice", ("admins",), 2), ("public",), False),
            BenchmarkQuestion("q2", "Quel est le code ambre zephyr ?", AuthorizationContext("a", "alice", ("admins",), 2), ("secret-a",), False),
            BenchmarkQuestion("q3", "Quel est le code cobalt orion ?", AuthorizationContext("a", "alice", ("admins",), 2), (), True),
        ]
        report, cases = run_lexical_benchmark(documents, questions, k=10)
        self.assertEqual(report.recall_at_k, 1.0)
        self.assertEqual(report.abstention_recall, 1.0)
        self.assertTrue(report.security_gate_passed)
        self.assertIn("public", cases[0].retrieved_chunk_ids)
        self.assertEqual(cases[2].retrieved_chunk_ids, ())


if __name__ == "__main__":
    unittest.main()
