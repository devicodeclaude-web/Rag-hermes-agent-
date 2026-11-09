import copy
import pickle
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

    def test_terminal_statuses_keep_failures_in_required_abstention_denominator(self):
        cases = [
            EvaluationCase("answered", ("c1",), ("c1",), (), False, False, ()),
            EvaluationCase("abstained", (), (), (), True, True, ()),
            EvaluationCase("acl-failed", (), (), (), True, False, (), technical_failure="acl_error"),
            EvaluationCase("backend-failed", (), (), (), True, False, (), technical_failure="backend_error"),
        ]
        report = evaluate(cases, k=1)
        self.assertEqual(report.terminal_statuses, (
            ("abstained", "abstained"),
            ("acl-failed", "acl_error"),
            ("answered", "answered"),
            ("backend-failed", "backend_error"),
        ))
        self.assertEqual(report.case_count, 4)
        self.assertEqual(report.acl_error_count, 1)
        self.assertEqual(report.backend_error_count, 1)
        self.assertAlmostEqual(report.abstention_recall, 1 / 3)
        self.assertEqual(report.abstention_precision, 1.0)

    def test_abstention_precision_lower_bound_charges_failures_on_answerable_cases(self):
        """A failure on an answerable case is charged as a false-positive abstention.

        Point precision is inflatable: a system that would have wrongly abstained
        but crashed instead loses its false positive. The published bound charges
        it back. A failure on a case that SHOULD abstain is never charged: in the
        no-failure counterfactual it could only have added a true positive or a
        false negative, neither of which inflates precision.
        """
        cases = [
            EvaluationCase("true-abstention", (), (), (), True, True, ()),
            EvaluationCase(
                "answerable-crashed", ("c1",), (), (), False, False, (),
                technical_failure="backend_error",
            ),
            EvaluationCase(
                "required-crashed", (), (), (), True, False, (),
                technical_failure="acl_error",
            ),
        ]
        report = evaluate(cases, k=1)
        self.assertEqual(report.abstention_precision, 1.0)
        self.assertEqual(report.abstention_precision_lower_bound, 0.5)

    def test_citation_precision_lower_bound_charges_citations_of_failed_cases(self):
        """Citations recorded on a failed case are charged as unsupported.

        Point citation precision is inflatable the same way: excluding failed
        cases erases their bad citations. The bound keeps every OBSERVED citation
        in the denominator. Honest limit: a case that failed before emitting any
        citation records none, so the bound cannot charge it -- it covers
        observed citations only, not citations the run never produced.
        """
        cases = [
            EvaluationCase("good", ("c1",), ("c1",), ("c1",), False, False, ()),
            EvaluationCase(
                "crashed-after-citing", ("c9",), ("zz",), ("zz",), False, False, (),
                technical_failure="backend_error",
            ),
        ]
        report = evaluate(cases, k=1)
        self.assertEqual(report.citation_precision, 1.0)
        self.assertEqual(report.citation_precision_lower_bound, 0.5)

    def test_strict_citation_lower_bounds_charge_failed_case_citations_as_invalid(self):
        """The 100 % structural-validity bar of §6 must not be inflatable either.

        Strict metrics are judged only on eligible cases, so a failed case's
        invalid citations vanish from both the numerator and the denominator.
        The bounds charge every observed citation of a failed case as invalid
        AND unsupported, which is the worst case consistent with the evidence.
        """
        cases = [
            EvaluationCase(
                "good", ("c1",), ("c1",), ("c1",), False, False, (),
                citation_judgments=(CitationJudgment("claim", "c1", True, True),),
            ),
            EvaluationCase(
                "crashed-after-citing", ("c9",), ("zz",), ("zz",), False, False, (),
                technical_failure="backend_error",
            ),
        ]
        report = evaluate(cases, k=1)
        self.assertEqual(report.citation_validity_precision, 1.0)
        self.assertEqual(report.citation_support_precision, 1.0)
        self.assertEqual(report.citation_validity_precision_lower_bound, 0.5)
        self.assertEqual(report.citation_support_precision_lower_bound, 0.5)

    def test_strict_citation_lower_bounds_are_unavailable_without_judgments(self):
        cases = [EvaluationCase("a", ("c1",), ("c1",), ("c1",), False, False, ())]
        report = evaluate(cases, k=1)
        self.assertIsNone(report.citation_validity_precision)
        self.assertIsNone(report.citation_support_precision)
        self.assertIsNone(report.citation_validity_precision_lower_bound)
        self.assertIsNone(report.citation_support_precision_lower_bound)
        self.assertEqual(len(report.terminal_statuses), report.case_count)

    def test_terminal_statuses_are_sorted_and_declare_their_source(self):
        """Published statuses must not make a reordering look like a divergence.

        `terminal_statuses` enters the hashed perimeter of any receipt built from
        this report (`report_sha256` is computed over canonical JSON), and
        canonical JSON sorts object keys but NOT array elements: emitting input
        order would change that hash on a mere dataset reshuffle, with no metric
        moving. Sorting by case_id removes that false signal. Integrity of the
        committed eval artefacts is uneven, so the reasoning lands differently per
        file: only `bge_m3_human_154_execution_receipt.json` carries an internal
        `report_sha256`; the dense and human-lexical reports are pinned by a side
        `.sha256`; the GPU smoke by `AUDIT/preuves/SHA256SUMS` and `README.md`;
        the bm25 report by `candidate_sha256` and its own `SHA256SUMS`; and
        `synthetic-eval-report.json` / `lexical_smoke_report.json` are pinned
        by nothing at all.

        The source flag puts the caveat in the EVIDENCE rather than only in the
        docs: it states what was OBSERVED (no runtime error reached the scorer),
        never that a pipeline wiring exists.
        """
        unsorted_cases = [
            EvaluationCase("z-case", (), (), (), True, True, ()),
            EvaluationCase("a-case", ("c1",), ("c1",), (), False, False, ()),
            EvaluationCase("m-case", ("c2",), ("c2",), (), False, False, ()),
        ]
        report = evaluate(unsorted_cases, k=1)
        self.assertEqual(report.terminal_statuses, (
            ("a-case", "answered"),
            ("m-case", "answered"),
            ("z-case", "abstained"),
        ))
        self.assertEqual(report.terminal_status_source, "no_runtime_error_observed")
        # Non-vacuous on a 3-case set: completeness AND order are both checked.
        self.assertEqual(len(report.terminal_statuses), report.case_count)

        with_failure = [
            EvaluationCase("a-case", ("c1",), ("c1",), (), False, False, ()),
            EvaluationCase(
                "b-case", (), (), (), True, False, (), technical_failure="acl_error"
            ),
        ]
        self.assertEqual(
            evaluate(with_failure, k=1).terminal_status_source,
            "runtime_errors_observed",
        )

    def test_scorer_rechecks_exclusivity_on_cases_that_bypassed_the_constructor(self):
        """Constructor validation is not enough: evaluate() re-checks, fail-closed.

        `__post_init__` makes the invariant true for every normal construction,
        but object.__new__, copy.deepcopy and pickle all bypass it -- each of the
        three is exercised here, not just asserted. Dropping the scorer's guard
        was a REGRESSION: a forged case published a failure status while
        `terminal_status_source` still claimed `no_runtime_error_observed`, and
        an unknown label such as "timeout" was emitted outside the declared
        TerminalStatus literal while counting in no error counter at all.

        The regexes match the SCORER's wording only ("scorer re-check", "reached
        the scorer"); the constructor's messages lack those suffixes, so these
        assertions fail if the guard moves back upstream and leaves the scorer
        open.
        """
        def forge(**over):
            case = object.__new__(EvaluationCase)
            fields = dict(
                case_id="forged", relevant_chunk_ids=(), retrieved_chunk_ids=(),
                cited_chunk_ids=(), should_abstain=True, did_abstain=True,
                leaked_chunk_ids=(), technical_failure="backend_error",
                citation_judgments=None, retrieved_relevance_ids_by_rank=None,
            )
            fields.update(over)
            for name, value in fields.items():
                object.__setattr__(case, name, value)
            return case

        # Vector 1: object.__new__ skips __init__ entirely.
        with self.assertRaisesRegex(ValueError, "abstention \\(scorer re-check\\)"):
            evaluate([forge()], k=1)

        # Vector 2: deepcopy of a LEGAL case, then frozen-dataclass mutation.
        smuggled = copy.deepcopy(
            EvaluationCase("smuggled", (), (), (), True, True, ())
        )
        object.__setattr__(smuggled, "technical_failure", "backend_error")
        with self.assertRaisesRegex(ValueError, "abstention \\(scorer re-check\\)"):
            evaluate([smuggled], k=1)

        # Vector 3: pickle round-trip preserves the forged state.
        unpickled = pickle.loads(pickle.dumps(forge()))
        self.assertEqual(
            (unpickled.technical_failure, unpickled.did_abstain),
            ("backend_error", True),
        )
        with self.assertRaisesRegex(ValueError, "abstention \\(scorer re-check\\)"):
            evaluate([unpickled], k=1)

        with self.assertRaisesRegex(ValueError, "unknown technical failure.*reached the scorer"):
            evaluate([forge(technical_failure="timeout", did_abstain=False)], k=1)

        # A non-str case_id would also crash the sort of terminal_statuses with
        # an opaque TypeError; refuse it explicitly instead.
        with self.assertRaisesRegex(ValueError, "case_id must be a string"):
            evaluate([forge(case_id=7, did_abstain=False, technical_failure=None)], k=1)

    def test_terminal_statuses_reject_duplicate_case_ids(self):
        cases = [
            EvaluationCase("same", (), (), (), True, True, ()),
            EvaluationCase("same", (), (), (), True, False, (), technical_failure="acl_error"),
        ]
        with self.assertRaisesRegex(ValueError, "duplicate case_id"):
            evaluate(cases, k=1)

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
        """The constructor refuses the contradiction -- first of two gates.

        Validating only inside evaluate() left `terminal_status` able to lie: it
        prioritises the failure and never signals the contradiction, so a case
        built directly reported `acl_error` while also claiming an abstention.
        This gate makes NORMAL construction fail closed; it is NOT a property of
        the type -- object.__new__, deepcopy and pickle bypass __post_init__,
        which is why evaluate() re-checks (see the companion test below).
        """
        with self.assertRaisesRegex(ValueError, "technical failure.*abstention"):
            EvaluationCase(
                "backend-down",
                (),
                (),
                (),
                True,
                True,
                (),
                technical_failure="backend_error",
            )

    def test_unknown_technical_failure_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown technical failure"):
            EvaluationCase(
                "backend-down",
                (),
                (),
                (),
                True,
                False,
                (),
                technical_failure="timeout",  # type: ignore[arg-type]
            )

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
