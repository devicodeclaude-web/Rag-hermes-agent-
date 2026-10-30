import unittest

from rag_hermes.evaluation import CitationJudgment, EvaluationCase, evaluate


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

    def test_strict_citation_judgments_do_not_change_legacy_citation_precision(self):
        case = EvaluationCase(
            case_id="q1",
            relevant_chunk_ids=("c1", "c2"),
            retrieved_chunk_ids=("c1", "c2"),
            cited_chunk_ids=("c1", "c2"),
            should_abstain=False,
            did_abstain=False,
            leaked_chunk_ids=(),
            citation_judgments=(
                CitationJudgment("claim-1", "c1", is_valid=True, supports_claim=True),
                CitationJudgment("claim-2", "c2", is_valid=False, supports_claim=False),
            ),
        )

        report = evaluate([case], k=2)

        self.assertEqual(report.citation_validity_precision, 0.5)
        self.assertEqual(report.citation_support_precision, 0.5)
        self.assertEqual(report.citation_precision, 1.0)

    def test_citation_support_is_judged_per_claim_occurrence(self):
        case = EvaluationCase(
            case_id="q1",
            relevant_chunk_ids=("c1",),
            retrieved_chunk_ids=("c1",),
            cited_chunk_ids=("c1", "c1"),
            should_abstain=False,
            did_abstain=False,
            leaked_chunk_ids=(),
            citation_judgments=(
                CitationJudgment("claim-1", "c1", is_valid=True, supports_claim=True),
                CitationJudgment("claim-2", "c1", is_valid=True, supports_claim=False),
            ),
        )

        report = evaluate([case], k=1)

        self.assertEqual(report.citation_validity_precision, 1.0)
        self.assertEqual(report.citation_support_precision, 0.5)

    def test_strict_citation_metrics_are_unavailable_without_judgments(self):
        case = EvaluationCase(
            case_id="q1",
            relevant_chunk_ids=("c1",),
            retrieved_chunk_ids=("c1",),
            cited_chunk_ids=("c1",),
            should_abstain=False,
            did_abstain=False,
            leaked_chunk_ids=(),
        )

        report = evaluate([case], k=1)

        self.assertIsNone(report.citation_validity_precision)
        self.assertIsNone(report.citation_support_precision)

        incomplete_report = evaluate(
            [
                EvaluationCase(
                    case_id="q2",
                    relevant_chunk_ids=("c1",),
                    retrieved_chunk_ids=("c1",),
                    cited_chunk_ids=("c1",),
                    should_abstain=False,
                    did_abstain=False,
                    leaked_chunk_ids=(),
                    citation_judgments=(),
                )
            ],
            k=1,
        )
        self.assertIsNone(incomplete_report.citation_validity_precision)
        self.assertIsNone(incomplete_report.citation_support_precision)

    def test_citations_on_technical_failures_are_excluded(self):
        cases = [
            EvaluationCase(
                "answered",
                ("relevant",),
                ("cited",),
                ("cited",),
                False,
                False,
                (),
                citation_judgments=(
                    CitationJudgment("claim", "cited", True, True),
                ),
            ),
            EvaluationCase(
                "acl-down",
                ("acl-citation",),
                ("acl-citation",),
                ("acl-citation",),
                False,
                False,
                (),
                technical_failure="acl_error",
                citation_judgments=(
                    CitationJudgment("claim", "acl-citation", False, False),
                ),
            ),
            EvaluationCase(
                "backend-down",
                ("backend-citation",),
                ("backend-citation",),
                ("backend-citation",),
                False,
                False,
                (),
                technical_failure="backend_error",
                citation_judgments=(
                    CitationJudgment("claim", "backend-citation", False, False),
                ),
            ),
        ]

        report = evaluate(cases, k=1)

        self.assertEqual(report.citation_precision, 0.0)
        self.assertEqual(report.citation_validity_precision, 1.0)
        self.assertEqual(report.citation_support_precision, 1.0)

    def test_abstention_precision_and_recall_are_separate(self):
        cases = [
            EvaluationCase("a", (), (), (), True, True, ()),
            EvaluationCase("b", (), (), (), True, False, ()),
            EvaluationCase("c", ("c1",), ("c1",), (), False, True, ()),
        ]
        report = evaluate(cases, k=10)
        self.assertEqual(report.abstention_precision, 0.5)
        self.assertEqual(report.abstention_recall, 0.5)

    def test_backend_failure_is_not_counted_as_abstention(self):
        cases = [
            EvaluationCase("a", (), (), (), True, True, ()),
            EvaluationCase(
                "backend-down",
                (),
                (),
                (),
                True,
                False,
                (),
                technical_failure="backend_error",
            ),
        ]

        report = evaluate(cases, k=10)

        self.assertEqual(report.abstention_precision, 1.0)
        self.assertEqual(report.abstention_recall, 0.5)
        self.assertEqual(report.backend_error_count, 1)
        self.assertEqual(report.acl_error_count, 0)

    def test_technical_failure_cannot_be_recorded_as_abstention(self):
        case = EvaluationCase(
            "backend-down",
            (),
            (),
            (),
            True,
            True,
            (),
            technical_failure="backend_error",
        )

        with self.assertRaisesRegex(ValueError, "technical failure.*abstention"):
            evaluate([case], k=10)

    def test_unknown_technical_failure_is_rejected(self):
        case = EvaluationCase(
            "backend-down",
            (),
            (),
            (),
            True,
            False,
            (),
            technical_failure="timeout",  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(ValueError, "unknown technical failure"):
            evaluate([case], k=10)

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

    def test_ranked_relevance_map_must_match_retrieved_labels(self):
        forged = EvaluationCase(
            "q",
            ("r",),
            ("x",),
            (),
            False,
            False,
            (),
            retrieved_relevance_ids_by_rank=(("r",),),
        )

        with self.assertRaisesRegex(ValueError, "ranked relevance map"):
            evaluate([forged], k=1)

    def test_k_must_be_a_strict_positive_integer(self):
        case = EvaluationCase("q", ("r",), ("r",), (), False, False, ())

        for invalid_k in (True, 1.5, "1", 0, -1):
            with self.subTest(k=invalid_k):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    evaluate([case], k=invalid_k)  # type: ignore[arg-type]

    def test_empty_case_set_is_invalid(self):
        with self.assertRaises(ValueError):
            evaluate([], k=10)


if __name__ == "__main__":
    unittest.main()
