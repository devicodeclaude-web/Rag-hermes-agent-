import unittest

from rag_hermes.evaluation import EvaluationCase, evaluate


class EvaluationTests(unittest.TestCase):
    def test_recall_at_k_and_mrr(self):
        cases = [
            EvaluationCase(
                case_id="q1",
                relevant_chunk_ids=("c2",),
                retrieved_chunk_ids=("c1", "c2", "c3"),
                cited_chunk_ids=("c2",),
                should_abstain=False,
                did_abstain=False,
                leaked_chunk_ids=(),
            ),
            EvaluationCase(
                case_id="q2",
                relevant_chunk_ids=("c4",),
                retrieved_chunk_ids=("c1", "c3", "c4"),
                cited_chunk_ids=("c4",),
                should_abstain=False,
                did_abstain=False,
                leaked_chunk_ids=(),
            ),
        ]
        report = evaluate(cases, k=2)
        self.assertEqual(report.recall_at_k, 0.5)
        self.assertAlmostEqual(report.mrr, (1 / 2 + 1 / 3) / 2)

    def test_citation_precision_counts_only_relevant_citations(self):
        case = EvaluationCase(
            case_id="q1",
            relevant_chunk_ids=("c1",),
            retrieved_chunk_ids=("c1", "c2"),
            cited_chunk_ids=("c1", "c2"),
            should_abstain=False,
            did_abstain=False,
            leaked_chunk_ids=(),
        )
        self.assertEqual(evaluate([case], k=2).citation_precision, 0.5)

    def test_abstention_precision_and_recall_are_separate(self):
        cases = [
            EvaluationCase("a", (), (), (), True, True, ()),
            EvaluationCase("b", (), (), (), True, False, ()),
            EvaluationCase("c", ("c1",), ("c1",), (), False, True, ()),
        ]
        report = evaluate(cases, k=10)
        self.assertEqual(report.abstention_precision, 0.5)
        self.assertEqual(report.abstention_recall, 0.5)

    def test_any_acl_leak_fails_security_gate(self):
        case = EvaluationCase(
            case_id="leak",
            relevant_chunk_ids=(),
            retrieved_chunk_ids=("foreign-secret",),
            cited_chunk_ids=(),
            should_abstain=True,
            did_abstain=True,
            leaked_chunk_ids=("foreign-secret",),
        )
        report = evaluate([case], k=10)
        self.assertEqual(report.leak_count, 1)
        self.assertFalse(report.security_gate_passed)

    def test_empty_case_set_is_invalid(self):
        with self.assertRaises(ValueError):
            evaluate([], k=10)


if __name__ == "__main__":
    unittest.main()
