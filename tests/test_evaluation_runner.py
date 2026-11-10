from __future__ import annotations

from dataclasses import replace
from typing import cast
import unittest

from rag_hermes.acl import AuthorizationContext, Chunk
from rag_hermes.evaluation_runner import (
    CaseExecutionError,
    RetrievedChunk,
    build_service_answer_fn,
    run_evaluation,
)
from rag_hermes.generator import GenerationError
from rag_hermes.retrieval import CanonicalAclError
from rag_hermes.ingestion import Document
from rag_hermes.service import RagService

PINNED_REVISION = "b682a98ab8cb30c4f0561021e0ff9f41e5156526"
PINNED_SHA = "af0631abbffaab14b180abc4531497665a6104d6685328d6abbe53a565c53866"


def _hash(passage: str) -> str:
    import hashlib

    return hashlib.sha256(passage.encode("utf-8")).hexdigest()


DOC_CONTENT = "alpha installer Hermes avec pipx omega configurer ensuite"


def _documents():
    return {"guide": {"content": DOC_CONTENT, "visibility": "public"}}


def _manifest():
    return {"source_revision": PINNED_REVISION, "corpus_manifest_sha": PINNED_SHA}


def _answerable_case():
    passage = "installer Hermes avec pipx"
    start = DOC_CONTENT.index(passage)
    return {
        "case_id": "q-1",
        "question": "Comment installer Hermes ?",
        "language": "en",
        "track": "en2en",
        "category": "simple",
        "access_scope": "public",
        "question_provenance": "human_task_without_corpus_view",
        "should_abstain": False,
        "unanswerable_reason": None,
        "reference_status": "validated",
        "source_revision": PINNED_REVISION,
        "corpus_manifest_sha": PINNED_SHA,
        "relevance_spans": [
            {
                "document_id": "guide",
                "start_char": start,
                "end_char": start + len(passage),
                "passage_sha256": _hash(passage),
                "relevance_grade": 2,
            }
        ],
    }


def _abstention_case():
    return {
        "case_id": "q-2",
        "question": "Quelle constante lunaire ?",
        "language": "en",
        "track": "en2en",
        "category": "no_answer",
        "access_scope": "public",
        "question_provenance": "human_task_without_corpus_view",
        "should_abstain": True,
        "unanswerable_reason": "outside_corpus_scope",
        "reference_status": "validated",
        "source_revision": PINNED_REVISION,
        "corpus_manifest_sha": PINNED_SHA,
        "relevance_spans": [],
    }


def _chunk(chunk_id: str, document_id: str, start: int, end: int) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=DOC_CONTENT[start:end],
        tenant_id="public",
        visibility="public",
        owner_id="system",
        allowed_groups=(),
        allowed_users=(),
        classification=0,
        doc_version=1,
        source_sha="a" * 64,
        source_uri="synthetic://guide",
        start_offset=start,
        end_offset=end,
    )


class EvaluationRunnerTests(unittest.TestCase):
    def test_service_adapter_runs_the_real_answer_path(self) -> None:
        context = AuthorizationContext(
            tenant_id="public",
            user_id="evaluator",
            groups=(),
            clearance=0,
        )
        service = RagService(top_k=1)
        service.import_document(
            Document(
                document_id="guide",
                content=DOC_CONTENT,
                tenant_id="public",
                visibility="public",
                owner_id="evaluator",
                allowed_groups=(),
                allowed_users=(),
                classification=0,
                doc_version=1,
                source_uri="synthetic://guide",
            ),
            context=context,
        )
        resolved_cases = []

        def context_for_case(case):
            resolved_cases.append(case["case_id"])
            return context

        answer_fn = build_service_answer_fn(service, context_for_case)
        report = run_evaluation(
            [_answerable_case()],
            _documents(),
            _manifest(),
            answer_fn,
            k=1,
        )

        self.assertEqual(resolved_cases, ["q-1"])
        self.assertEqual(report.recall_at_k, 1.0)
        self.assertEqual(report.mrr, 1.0)
        self.assertEqual(report.citation_precision, 1.0)
        self.assertTrue(report.security_gate_passed)

    def test_answerable_case_maps_overlapping_chunk_as_relevant(self) -> None:
        # A chunk covering the relevance span (char overlap) must count as a hit.
        overlapping = _chunk("guide:0", "guide", 0, 40)  # covers "installer Hermes avec pipx"
        distractor = _chunk("guide:1", "guide", 41, len(DOC_CONTENT))

        def answer_fn(question, case):
            return (
                [RetrievedChunk(overlapping), RetrievedChunk(distractor)],
                [RetrievedChunk(overlapping)],
                False,
            )

        report = run_evaluation(
            [_answerable_case()], _documents(), _manifest(), answer_fn, k=5
        )

        self.assertEqual(report.case_count, 1)
        self.assertEqual(report.recall_at_k, 1.0)
        self.assertEqual(report.mrr, 1.0)
        self.assertEqual(report.leak_count, 0)
        self.assertTrue(report.security_gate_passed)

    def test_non_overlapping_retrieval_is_a_miss(self) -> None:
        far = _chunk("guide:1", "guide", 41, len(DOC_CONTENT))

        def answer_fn(question, case):
            return ([RetrievedChunk(far)], [], False)

        report = run_evaluation(
            [_answerable_case()], _documents(), _manifest(), answer_fn, k=5
        )
        self.assertEqual(report.recall_at_k, 0.0)
        self.assertEqual(report.mrr, 0.0)

    def test_abstention_case_scores_abstention_when_service_abstains(self) -> None:
        def answer_fn(question, case):
            return ([], [], True)

        report = run_evaluation(
            [_abstention_case()], _documents(), _manifest(), answer_fn, k=5
        )
        self.assertEqual(report.abstention_recall, 1.0)
        self.assertEqual(report.abstention_precision, 1.0)

    def test_invalid_case_is_rejected_before_running(self) -> None:
        bad = _answerable_case()
        bad["source_revision"] = "0" * 40

        def answer_fn(question, case):
            raise AssertionError("answer_fn must not run on an invalid case")

        with self.assertRaisesRegex(ValueError, "source_revision"):
            run_evaluation([bad], _documents(), _manifest(), answer_fn, k=5)

    def test_all_cases_are_validated_before_any_answer_runs(self) -> None:
        valid = _answerable_case()
        invalid = _answerable_case()
        invalid["case_id"] = "q-invalid"
        invalid["source_revision"] = "0" * 40
        calls = []

        def answer_fn(question, case):
            calls.append(case["case_id"])
            return ([], [], False)

        with self.assertRaisesRegex(ValueError, "source_revision"):
            run_evaluation(
                [valid, invalid], _documents(), _manifest(), answer_fn, k=5
            )

        self.assertEqual(calls, [])

    def test_one_ranked_chunk_can_cover_multiple_relevance_spans(self) -> None:
        case = _answerable_case()
        second_passage = "configurer ensuite"
        second_start = DOC_CONTENT.index(second_passage)
        case["relevance_spans"].append(
            {
                "document_id": "guide",
                "start_char": second_start,
                "end_char": second_start + len(second_passage),
                "passage_sha256": _hash(second_passage),
                "relevance_grade": 2,
            }
        )
        distractor = _chunk("guide:distractor", "guide", 0, 5)
        covering = _chunk("guide:covering", "guide", 6, len(DOC_CONTENT))

        def answer_fn(question, validated_case):
            return (
                [RetrievedChunk(distractor), RetrievedChunk(covering)],
                [RetrievedChunk(covering)],
                False,
            )

        report = run_evaluation(
            [case], _documents(), _manifest(), answer_fn, k=2
        )

        self.assertEqual(report.recall_at_k, 1.0)
        self.assertEqual(report.mrr, 0.5)
        self.assertEqual(report.citation_precision, 1.0)

    def test_known_document_chunk_text_must_match_canonical_slice(self) -> None:
        valid = _chunk("guide:tampered", "guide", 6, 20)
        tampered = replace(valid, text="tampered text")

        def answer_fn(question, case):
            return ([RetrievedChunk(tampered)], [], False)

        with self.assertRaisesRegex(ValueError, "text does not match canonical"):
            run_evaluation(
                [_answerable_case()], _documents(), _manifest(), answer_fn, k=5
            )

    def test_known_document_chunk_offsets_must_stay_within_canonical_content(self) -> None:
        invalid = _chunk("guide:invalid", "guide", 1, len(DOC_CONTENT) + 100)

        def answer_fn(question, case):
            return ([RetrievedChunk(invalid)], [], False)

        with self.assertRaisesRegex(ValueError, "outside canonical document"):
            run_evaluation(
                [_answerable_case()], _documents(), _manifest(), answer_fn, k=5
            )

    def test_non_matching_chunk_id_cannot_collide_with_span_label(self) -> None:
        case = _answerable_case()
        span = case["relevance_spans"][0]
        colliding_id = (
            f"span:guide#span0:{span['start_char']}-{span['end_char']}"
        )
        non_matching = _chunk(
            colliding_id, "guide", span["end_char"], len(DOC_CONTENT)
        )

        def answer_fn(question, validated_case):
            return ([RetrievedChunk(non_matching)], [], False)

        report = run_evaluation(
            [case], _documents(), _manifest(), answer_fn, k=5
        )

        self.assertEqual(report.recall_at_k, 0.0)
        self.assertEqual(report.mrr, 0.0)

    def test_chunk_offsets_must_be_strict_integers(self) -> None:
        valid = _chunk("guide:invalid-type", "guide", 6, 20)
        for field, value in (("start_offset", "6"), ("end_offset", 20.0)):
            with self.subTest(field=field, value=value):
                invalid = replace(valid, **{field: value})

                def answer_fn(question, case):
                    return ([RetrievedChunk(invalid)], [], False)

                with self.assertRaisesRegex(ValueError, "chunk offsets must be integers"):
                    run_evaluation(
                        [_answerable_case()], _documents(), _manifest(), answer_fn, k=5
                    )

    def test_retrieved_chunk_offsets_must_form_a_non_empty_interval(self) -> None:
        span_start = _answerable_case()["relevance_spans"][0]["start_char"]
        for start, end in ((span_start, span_start), (span_start + 1, span_start)):
            with self.subTest(start=start, end=end):
                invalid = _chunk("guide:invalid", "guide", start, end)

                def answer_fn(question, case):
                    return ([RetrievedChunk(invalid)], [], False)

                with self.assertRaisesRegex(ValueError, "invalid chunk offsets"):
                    run_evaluation(
                        [_answerable_case()], _documents(), _manifest(), answer_fn, k=5
                    )

    def test_relevance_grade_must_be_a_strict_integer(self) -> None:
        for invalid_grade in (True, 1.0, "1"):
            with self.subTest(grade=invalid_grade):
                invalid = _answerable_case()
                invalid["relevance_spans"][0]["relevance_grade"] = invalid_grade

                with self.assertRaisesRegex(
                    ValueError, "relevance_grade must be integer 1 or 2"
                ):
                    run_evaluation(
                        [invalid],
                        _documents(),
                        _manifest(),
                        lambda question, case: ([], [], False),
                        k=5,
                    )

    def test_span_offsets_must_be_strict_integers_before_answer_runs(self) -> None:
        for field, value in (("start_char", "6"), ("end_char", 30.0)):
            with self.subTest(field=field, value=value):
                invalid = _answerable_case()
                invalid["relevance_spans"][0][field] = value
                calls = []

                def answer_fn(question, case):
                    calls.append(case["case_id"])
                    return ([], [], False)

                with self.assertRaisesRegex(ValueError, "must be an integer"):
                    run_evaluation(
                        [invalid], _documents(), _manifest(), answer_fn, k=5
                    )
                self.assertEqual(calls, [])

    def test_duplicate_spans_are_rejected_before_answer_runs(self) -> None:
        invalid = _answerable_case()
        invalid["relevance_spans"].append(dict(invalid["relevance_spans"][0]))
        calls = []

        def answer_fn(question, case):
            calls.append(case["case_id"])
            return ([], [], False)

        with self.assertRaisesRegex(ValueError, "duplicate relevance span"):
            run_evaluation(
                [invalid], _documents(), _manifest(), answer_fn, k=5
            )
        self.assertEqual(calls, [])

    def test_duplicate_case_ids_are_rejected_before_answer_runs(self) -> None:
        first = _answerable_case()
        duplicate = _answerable_case()
        calls = []

        def answer_fn(question, case):
            calls.append(case["case_id"])
            return ([], [], False)

        with self.assertRaisesRegex(ValueError, "duplicate case_id"):
            run_evaluation(
                [first, duplicate], _documents(), _manifest(), answer_fn, k=5
            )
        self.assertEqual(calls, [])

    def test_case_should_abstain_must_be_a_bool_before_answer_runs(self) -> None:
        invalid = _answerable_case()
        invalid["should_abstain"] = "false"
        calls = []

        def answer_fn(question, case):
            calls.append(case["case_id"])
            return ([], [], False)

        with self.assertRaisesRegex(ValueError, "should_abstain must be a bool"):
            run_evaluation(
                [invalid], _documents(), _manifest(), answer_fn, k=5
            )
        self.assertEqual(calls, [])

    def test_answer_abstained_flag_must_be_a_bool(self) -> None:
        def answer_fn(question, case):
            return ([], [], "false")

        with self.assertRaisesRegex(ValueError, "abstained must be a bool"):
            run_evaluation(
                [_answerable_case()],
                _documents(),
                _manifest(),
                answer_fn,  # type: ignore[arg-type]
                k=5,
            )

    def test_k_must_be_a_strict_positive_integer_before_answer_runs(self) -> None:
        for invalid_k in (True, 1.5, "5", 0, -1):
            with self.subTest(k=invalid_k):
                calls = []

                def answer_fn(question, case):
                    calls.append(case["case_id"])
                    return ([], [], False)

                with self.assertRaisesRegex(ValueError, "positive integer"):
                    run_evaluation(
                        [_answerable_case()],
                        _documents(),
                        _manifest(),
                        answer_fn,
                        k=invalid_k,  # type: ignore[arg-type]
                    )
                self.assertEqual(calls, [])

    def test_unknown_document_stays_a_leak_even_if_explicitly_allowlisted(self) -> None:
        foreign = _chunk("secret:0", "unknown-document", 0, 10)

        def answer_fn(question, case):
            return ([RetrievedChunk(foreign)], [], False)

        report = run_evaluation(
            [_answerable_case()],
            _documents(),
            _manifest(),
            answer_fn,
            k=5,
            authorized_document_ids={"guide", "unknown-document"},
        )

        self.assertEqual(report.leak_count, 1)
        self.assertFalse(report.security_gate_passed)

    def test_cited_chunk_must_have_been_retrieved(self) -> None:
        cited_only = _chunk("guide:cited-only", "guide", 6, 30)

        def answer_fn(question, case):
            return ([], [RetrievedChunk(cited_only)], False)

        with self.assertRaisesRegex(ValueError, "citation was not retrieved"):
            run_evaluation(
                [_answerable_case()], _documents(), _manifest(), answer_fn, k=5
            )

    def test_default_authorization_respects_case_access_scope(self) -> None:
        documents = _documents()
        documents["private-guide"] = {
            "content": DOC_CONTENT,
            "visibility": "private",
        }
        private_chunk = _chunk("private:0", "private-guide", 0, 10)

        def answer_fn(question, case):
            return ([RetrievedChunk(private_chunk)], [], False)

        report = run_evaluation(
            [_answerable_case()], documents, _manifest(), answer_fn, k=5
        )

        self.assertEqual(report.leak_count, 1)
        self.assertFalse(report.security_gate_passed)

    def test_foreign_document_is_a_leak_without_explicit_authorized_set(self) -> None:
        foreign = _chunk("secret:0", "secret-doc", 0, 10)

        def answer_fn(question, case):
            return ([RetrievedChunk(foreign)], [], False)

        report = run_evaluation(
            [_answerable_case()], _documents(), _manifest(), answer_fn, k=5
        )

        self.assertEqual(report.leak_count, 1)
        self.assertFalse(report.security_gate_passed)

    def test_foreign_citation_is_counted_as_leak(self) -> None:
        foreign = _chunk("secret:0", "secret-doc", 0, 10)

        def answer_fn(question, case):
            item = RetrievedChunk(foreign)
            return ([item], [item], False)

        report = run_evaluation(
            [_answerable_case()],
            _documents(),
            _manifest(),
            answer_fn,
            k=5,
            authorized_document_ids={"guide"},
        )

        self.assertEqual(report.leak_count, 1)
        self.assertFalse(report.security_gate_passed)

    def test_foreign_document_retrieval_is_counted_as_leak(self) -> None:
        # A retrieved chunk from a document not in the authorized corpus is a leak.
        foreign = _chunk("secret:0", "secret-doc", 0, 10)

        def answer_fn(question, case):
            return ([RetrievedChunk(foreign)], [], False)

        report = run_evaluation(
            [_answerable_case()],
            _documents(),
            _manifest(),
            answer_fn,
            k=5,
            authorized_document_ids={"guide"},
        )
        self.assertEqual(report.leak_count, 1)
        self.assertFalse(report.security_gate_passed)

    def test_absent_evidence_abstains_while_a_failed_acl_barrier_errors(self) -> None:
        """The two paths must stay distinct, or abstention metrics are destroyed.

        A `no_answer` case legitimately finds nothing authorized and must score
        as `abstained`. Only an ACL barrier that FAILS CLOSED (PermissionError)
        becomes `acl_error`. If the service ever raised PermissionError on an
        empty result set, every honest abstention would be reclassified as a
        technical failure and the abstention recall would collapse -- this test
        pins the boundary from both sides.
        """
        context = AuthorizationContext(
            tenant_id="public", user_id="evaluator", groups=(), clearance=0
        )
        service = RagService(top_k=1)
        service.import_document(
            Document(
                document_id="guide",
                content=DOC_CONTENT,
                tenant_id="public",
                visibility="public",
                owner_id="evaluator",
                allowed_groups=(),
                allowed_users=(),
                classification=0,
                doc_version=1,
                source_uri="synthetic://guide",
            ),
            context=context,
        )

        # Side 1: nothing authorized matches -> honest abstention, no error.
        answer_fn = build_service_answer_fn(service, lambda case: context)
        retrieved, cited, abstained = answer_fn(
            "Quelle constante lunaire ?", _abstention_case()
        )
        self.assertTrue(abstained)
        self.assertEqual((len(retrieved), len(cited)), (0, 0))

        # Side 2: the barrier itself fails closed -> acl_error, never abstention.
        class _Barred:
            def answer_with_trace(self, question, *, context):
                raise CanonicalAclError("stale ACL index has no usable candidates")

        barred_fn = build_service_answer_fn(
            cast(RagService, _Barred()), lambda case: context
        )
        with self.assertRaises(CaseExecutionError) as caught:
            barred_fn("Quelle constante lunaire ?", _abstention_case())
        self.assertEqual(caught.exception.terminal_status, "acl_error")

    def test_service_adapter_translates_the_service_exception_vocabulary(self) -> None:
        """Only the adapter that KNOWS the service maps its exceptions.

        CanonicalAclError is what the canonical ACL bridge raises when it fails
        closed; GenerationError is the backend/generator failure. The mapping
        lives here, not in run_evaluation, because an arbitrary answer_fn could
        raise PermissionError for an unrelated reason (a filesystem denial, say)
        and recording that as an ACL error would be a false audit finding.
        """
        context = AuthorizationContext(
            tenant_id="public", user_id="evaluator", groups=(), clearance=0
        )

        class _Failing:
            def __init__(self, error):
                self._error = error

            def answer_with_trace(self, question, *, context):
                raise self._error

        for error, expected in (
            (CanonicalAclError("stale ACL index"), "acl_error"),
            (GenerationError("generator is unavailable"), "backend_error"),
        ):
            answer_fn = build_service_answer_fn(
                cast(RagService, _Failing(error)), lambda case: context
            )
            with self.assertRaises(CaseExecutionError) as caught:
                answer_fn("q?", _answerable_case())
            self.assertEqual(caught.exception.terminal_status, expected)
            # The original cause stays available to the operator...
            self.assertIs(caught.exception.__cause__, error)
            # ...but its text, which can carry a URL or credentials, is not
            # copied into the signalled error.
            self.assertNotIn(str(error), str(caught.exception))

    def test_storage_permission_error_does_not_become_acl_error(self) -> None:
        context = AuthorizationContext("public", "evaluator", (), 0)

        class _StorageDenied:
            def answer_with_trace(self, question, *, context):
                raise PermissionError("storage unavailable")

        answer_fn = build_service_answer_fn(
            cast(RagService, _StorageDenied()), lambda case: context
        )
        with self.assertRaisesRegex(PermissionError, "storage unavailable"):
            answer_fn("q?", _answerable_case())

    def test_service_adapter_lets_unknown_exceptions_propagate(self) -> None:
        context = AuthorizationContext(
            tenant_id="public", user_id="evaluator", groups=(), clearance=0
        )

        class _Buggy:
            def answer_with_trace(self, question, *, context):
                raise KeyError("harness bug")

        answer_fn = build_service_answer_fn(
            cast(RagService, _Buggy()), lambda case: context
        )
        with self.assertRaises(KeyError):
            answer_fn("q?", _answerable_case())

    def test_signalled_case_failure_is_recorded_as_its_terminal_status(self) -> None:
        """A case the harness could not execute becomes acl_error/backend_error.

        Until now run_evaluation set no technical_failure at all, so every report
        read `no_runtime_error_observed` and the terminal-status contract was
        decorative. A signalled failure must NOT be scored as an abstention: it
        stays in the case total, feeds its own counter, and leaves the predicted
        abstentions untouched.
        """
        def answer_fn(question, case):
            if case["case_id"] == "q-1":
                raise CaseExecutionError("acl_error", "canonical authority refused")
            return ([], [], True)

        report = run_evaluation(
            [_answerable_case(), _abstention_case()],
            _documents(),
            _manifest(),
            answer_fn,
            k=5,
        )

        self.assertEqual(
            report.terminal_statuses,
            (("q-1", "acl_error"), ("q-2", "abstained")),
        )
        self.assertEqual(report.terminal_status_source, "runtime_errors_observed")
        self.assertEqual(report.acl_error_count, 1)
        self.assertEqual(report.backend_error_count, 0)
        self.assertEqual(report.case_count, 2)
        # The failed case is answerable, so it is charged to the pessimistic
        # precision bound while the point estimate stays blind to it.
        self.assertEqual(report.abstention_precision, 1.0)
        self.assertEqual(report.abstention_precision_lower_bound, 0.5)

    def test_unexpected_exception_from_answer_fn_aborts_the_campaign(self) -> None:
        """Only SIGNALLED failures are classified; anything else must propagate.

        Catching broad exception classes here would turn a harness bug, a typo
        or a transport crash into a published `backend_error` -- a false audit
        finding in a component meant to produce evidence.
        """
        def answer_fn(question, case):
            raise RuntimeError("harness bug, not a backend failure")

        with self.assertRaisesRegex(RuntimeError, "harness bug"):
            run_evaluation(
                [_answerable_case()],
                _documents(),
                _manifest(),
                answer_fn,
                k=5,
            )


if __name__ == "__main__":
    unittest.main()
