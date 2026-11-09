"""A campaign must not be scorable unless the index audit opened AND re-closed.

CPU only: the answer function is a stub, so nothing here measures answer quality.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from rag_hermes.acl import AuthorizationContext
from rag_hermes.acl_authority import AclPolicy, CanonicalAclAuthority
from rag_hermes.evaluation_runner import RetrievedChunk, run_audited_evaluation
from rag_hermes.index_integrity import AuditedIndexSession, AuditedIndexSessionError
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_store import chunk_to_point

from test_evaluation_runner import (  # reuse the strict dataset fixtures
    DOC_CONTENT,
    _abstention_case,
    _answerable_case,
    _chunk,
    _documents,
    _manifest,
)


def _indexed_chunks():
    document = Document(
        document_id="guide",
        content=DOC_CONTENT,
        tenant_id="public",
        visibility="public",
        owner_id="system",
        allowed_groups=(),
        allowed_users=(),
        classification=0,
        doc_version=1,
        source_uri="synthetic://guide",
    )
    return chunk_document(document)


def _authority_for(chunks):
    return CanonicalAclAuthority({
        chunk.document_id: AclPolicy(
            tenant_id=chunk.tenant_id,
            visibility=chunk.visibility,
            owner_id=chunk.owner_id,
            allowed_groups=chunk.allowed_groups,
            allowed_users=chunk.allowed_users,
            classification=chunk.classification,
            acl_version=chunk.acl_version,
        )
        for chunk in chunks
    })

class AuditedCampaignTests(unittest.TestCase):
    def setUp(self):
        self.chunks = _indexed_chunks()
        self.points = [chunk_to_point(chunk, [1.0]) for chunk in self.chunks]
        self.authority = _authority_for(self.chunks)
        self.context_for_case = lambda case: AuthorizationContext(
            tenant_id="public", user_id="evaluator", groups=(), clearance=0
        )
        self.answered = []

        passage = "installer Hermes avec pipx"
        start = DOC_CONTENT.index(passage)
        retrieved = (RetrievedChunk(_chunk("c1", "guide", start, start + len(passage))),)

        def answer_fn(question, case, context):
            self.answered.append(case["case_id"])
            if case["should_abstain"]:
                return (), (), True
            return retrieved, retrieved, False

        self.answer_fn = answer_fn
        self.cases = [_answerable_case(), _abstention_case()]

    def _session(self, pages):
        remaining = list(pages)

        class FakeClient:
            def scroll_page(self, collection, *, limit, offset=None):
                return remaining.pop(0), None

        return AuditedIndexSession(FakeClient(), "chunks", self.chunks)

    def _run(self, session):
        return run_audited_evaluation(
            session,
            self.cases,
            _documents(),
            _manifest(),
            self.answer_fn,
            k=1,
            context_for_case=self.context_for_case,
            authority=self.authority,
        )

    def test_campaign_runs_between_two_successful_audits(self):
        report = self._run(self._session([self.points, self.points]))
        self.assertEqual(self.answered, ["q-1", "q-2"])
        self.assertEqual(report.case_count, 2)

    def test_failing_opening_audit_answers_no_case_at_all(self):
        # An index missing the canonical point: the opening audit must abort the
        # campaign before the first question is asked.
        session = self._session([[], self.points])
        with self.assertRaises(AuditedIndexSessionError):
            self._run(session)
        self.assertEqual(self.answered, [])

    def test_failing_closing_audit_yields_no_report(self):
        mutated = [dict(point, payload=dict(point["payload"])) for point in self.points]
        mutated[0]["payload"]["owner_id"] = "intruder"
        session = self._session([self.points, mutated])
        with self.assertRaises(AuditedIndexSessionError):
            self._run(session)
        # The cases did run, but no score may be reported from an index that
        # diverged mid-campaign.
        self.assertEqual(self.answered, ["q-1", "q-2"])

    def test_already_used_session_cannot_score_a_second_campaign(self):
        session = self._session([self.points, self.points])
        self._run(session)
        with self.assertRaisesRegex(ValueError, "already opened or finished"):
            self._run(session)

    def test_scoring_failure_still_closes_the_session(self):
        session = self._session([self.points, self.points])
        with self.assertRaisesRegex(ValueError, "k must be a positive integer"):
            run_audited_evaluation(
                session, self.cases, _documents(), _manifest(), self.answer_fn, k=0,
                context_for_case=self.context_for_case, authority=self.authority,
            )
        with self.assertRaisesRegex(ValueError, "already opened or finished"):
            session.open()

    def test_scoring_failure_burns_the_session_without_a_second_audit(self):
        audits = []
        points = self.points

        class CountingClient:
            def scroll_page(self, collection, *, limit, offset=None):
                audits.append(offset)
                return points, None

        session = AuditedIndexSession(CountingClient(), "chunks", self.chunks)
        with self.assertRaisesRegex(ValueError, "k must be a positive integer"):
            run_audited_evaluation(
                session, self.cases, _documents(), _manifest(), self.answer_fn, k=0,
                context_for_case=self.context_for_case, authority=self.authority,
            )
        # Only the opening audit ran: a failed campaign must not pay for (nor
        # pretend to report on) a closing audit, and Ctrl-C must not trigger a
        # full index scan on its way out.
        self.assertEqual(len(audits), 1)
        with self.assertRaisesRegex(ValueError, "already opened or finished"):
            session.open()

    def test_private_chunk_of_other_owner_is_a_leak_despite_two_clean_audits(self):
        def private_document(document_id, owner_id):
            return Document(
                document_id=document_id,
                content=DOC_CONTENT,
                tenant_id="tenant-a",
                visibility="private",
                owner_id=owner_id,
                allowed_groups=(),
                allowed_users=(),
                classification=0,
                doc_version=1,
                source_uri=f"synthetic://{document_id}",
            )

        alice_chunks = chunk_document(private_document("alice-doc", "alice"))
        bob_chunks = chunk_document(private_document("bob-doc", "bob"))
        all_chunks = [*alice_chunks, *bob_chunks]
        points = [chunk_to_point(chunk, [1.0]) for chunk in all_chunks]
        session = AuditedIndexSession(
            type("Client", (), {"scroll_page": lambda self, *a, **kw: (points, None)})(),
            "chunks", all_chunks,
        )
        case = _answerable_case()
        case["access_scope"] = "private"
        case["relevance_spans"][0]["document_id"] = "alice-doc"
        documents = {
            doc_id: {"content": DOC_CONTENT, "visibility": "private"}
            for doc_id in ("alice-doc", "bob-doc")
        }
        report = run_audited_evaluation(
            session, [case], documents, _manifest(),
            lambda question, case, context: ([RetrievedChunk(bob_chunks[0])], [], False), k=1,
            context_for_case=lambda case: AuthorizationContext(
                tenant_id="tenant-a", user_id="alice", groups=(), clearance=0
            ),
            authority=_authority_for(all_chunks),
        )
        self.assertEqual(report.leak_count, 1)
        self.assertFalse(report.security_gate_passed)

    def test_forged_chunk_acl_cannot_inherit_canonical_permission(self):
        forged = replace(self.chunks[0], owner_id="intruder")
        report = run_audited_evaluation(
            self._session([self.points, self.points]),
            [_answerable_case()], _documents(), _manifest(),
            lambda question, case, context: ([RetrievedChunk(forged)], [], False),
            k=1, context_for_case=self.context_for_case, authority=self.authority,
        )
        self.assertEqual(report.leak_count, 1)
        self.assertFalse(report.security_gate_passed)

    def test_audited_answer_receives_the_exact_scoring_context_once(self):
        calls = []
        resolved = AuthorizationContext("public", "evaluator", (), 0)

        def resolve(case):
            calls.append(("resolve", case["case_id"]))
            return resolved

        def answer(question, case, context):
            calls.append(("answer", context))
            return (), (), True

        report = run_audited_evaluation(
            self._session([self.points, self.points]),
            [_abstention_case()], _documents(), _manifest(), answer,
            k=1, context_for_case=resolve, authority=self.authority,
        )
        self.assertEqual(report.case_count, 1)
        self.assertEqual(calls, [("resolve", "q-2"), ("answer", resolved)])

    def test_contextual_service_adapter_uses_the_supplied_context(self):
        from rag_hermes.evaluation_runner import build_contextual_service_answer_fn
        from rag_hermes.service import RagService

        context = AuthorizationContext("public", "evaluator", (), 0)
        service = RagService(top_k=1)
        service.import_document(
            Document(
                document_id="guide", content=DOC_CONTENT,
                tenant_id="public", visibility="public", owner_id="evaluator",
                allowed_groups=(), allowed_users=(), classification=0,
                doc_version=1, source_uri="synthetic://guide",
            ),
            context=context,
        )
        calls = []
        original_answer = service.answer_with_trace
        def observed_answer(question, *, context):
            calls.append(context)
            return original_answer(question, context=context)
        service.answer_with_trace = observed_answer
        response = build_contextual_service_answer_fn(service)(
            _answerable_case()["question"], _answerable_case(), context
        )
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0], context)
        self.assertTrue(response[0])
        self.assertFalse(response[2])

    def test_canonical_document_visibility_must_agree_with_authority(self):
        docs = {"guide": {"content": DOC_CONTENT, "visibility": "private"}}
        case = _answerable_case()
        case["access_scope"] = "private"
        with self.assertRaisesRegex(ValueError, "visibility"):
            run_audited_evaluation(
                self._session([self.points, self.points]), [case], docs, _manifest(),
                self.answer_fn, k=1, context_for_case=self.context_for_case,
                authority=self.authority,
            )
        self.assertEqual(self.answered, [])

    def test_private_case_can_retrieve_authorized_global_public_document(self):
        private = Document(
            document_id="alice-doc", content=DOC_CONTENT, tenant_id="tenant-a",
            visibility="private", owner_id="alice", allowed_groups=(),
            allowed_users=(), classification=0, doc_version=1,
            source_uri="synthetic://alice-doc",
        )
        chunks = [*self.chunks, *chunk_document(private)]
        points = [chunk_to_point(chunk, [1.0]) for chunk in chunks]
        class Client:
            def scroll_page(self, collection, *, limit, offset=None):
                return points, None
        session = AuditedIndexSession(Client(), "chunks", chunks)
        case = _answerable_case()
        case["access_scope"] = "private"
        case["relevance_spans"][0]["document_id"] = "alice-doc"
        docs = {
            "guide": {"content": DOC_CONTENT, "visibility": "public"},
            "alice-doc": {"content": DOC_CONTENT, "visibility": "private"},
        }
        report = run_audited_evaluation(
            session, [case], docs, _manifest(),
            lambda question, case, context: ([RetrievedChunk(self.chunks[0])], [], False),
            k=1, context_for_case=lambda case: AuthorizationContext(
                "tenant-a", "alice", (), 0
            ),
            authority=_authority_for(chunks),
        )
        self.assertEqual(report.leak_count, 0)
        self.assertTrue(report.security_gate_passed)

    def test_subclass_overriding_audit_cannot_stand_in_for_session(self):
        class BypassedSession(AuditedIndexSession):
            def open(self):
                return None
            def close(self):
                return None

        session = BypassedSession(object(), "chunks", self.chunks)
        with self.assertRaisesRegex(TypeError, "AuditedIndexSession"):
            self._run(session)
        self.assertEqual(self.answered, [])

    def test_subclass_overriding_authority_cannot_stand_in(self):
        canonical_policy = self.authority.policy_for("guide")
        class BypassedAuthority(CanonicalAclAuthority):
            def policy_for(self, document_id):
                return canonical_policy
            def authorize(self, document_id, indexed_acl_version, context):
                return True, "allowed"

        with self.assertRaisesRegex(TypeError, "CanonicalAclAuthority"):
            run_audited_evaluation(
                self._session([self.points, self.points]), self.cases,
                _documents(), _manifest(), self.answer_fn, k=1,
                context_for_case=self.context_for_case,
                authority=BypassedAuthority({}),
            )
        self.assertEqual(self.answered, [])

    def test_private_reference_must_be_authorized_for_case_context(self):
        alice_doc = Document(
            document_id="alice-doc", content=DOC_CONTENT, tenant_id="tenant-a",
            visibility="private", owner_id="alice", allowed_groups=(),
            allowed_users=(), classification=0, doc_version=1,
            source_uri="synthetic://alice-doc",
        )
        chunks = chunk_document(alice_doc)
        points = [chunk_to_point(chunk, [1.0]) for chunk in chunks]
        class Client:
            def scroll_page(self, collection, *, limit, offset=None):
                return points, None
        session = AuditedIndexSession(Client(), "chunks", chunks)
        case = _answerable_case()
        case["access_scope"] = "private"
        case["relevance_spans"][0]["document_id"] = "alice-doc"
        with self.assertRaisesRegex(ValueError, "reference.*authorized"):
            run_audited_evaluation(
                session, [case],
                {"alice-doc": {"content": DOC_CONTENT, "visibility": "private"}},
                _manifest(), self.answer_fn, k=1,
                context_for_case=lambda case: AuthorizationContext(
                    "tenant-a", "bob", (), 0
                ),
                authority=_authority_for(chunks),
            )
        self.assertEqual(self.answered, [])

    def test_subclassed_acl_policy_cannot_override_reference_authorization(self):
        class BypassedPolicy(AclPolicy):
            def allows(self, context):
                return True

        private = Document(
            document_id="alice-doc", content=DOC_CONTENT, tenant_id="tenant-a",
            visibility="private", owner_id="alice", allowed_groups=(),
            allowed_users=(), classification=0, doc_version=1,
            source_uri="synthetic://alice-doc",
        )
        chunks = chunk_document(private)
        points = [chunk_to_point(chunk, [1.0]) for chunk in chunks]
        class Client:
            def scroll_page(self, collection, *, limit, offset=None):
                return points, None
        policy = _authority_for(chunks).policy_for("alice-doc")
        authority = CanonicalAclAuthority({"alice-doc": BypassedPolicy(**vars(policy))})
        case = _answerable_case()
        case["access_scope"] = "private"
        case["relevance_spans"][0]["document_id"] = "alice-doc"
        with self.assertRaisesRegex(ValueError, "ACL policy"):
            run_audited_evaluation(
                AuditedIndexSession(Client(), "chunks", chunks), [case],
                {"alice-doc": {"content": DOC_CONTENT, "visibility": "private"}},
                _manifest(), self.answer_fn, k=1,
                context_for_case=lambda case: AuthorizationContext("tenant-a", "bob", (), 0),
                authority=authority,
            )
        self.assertEqual(self.answered, [])

    def test_canonical_tenant_rejects_bool_integer_equivalence(self):
        typed_chunk = replace(self.chunks[0], tenant_id=True)
        point = chunk_to_point(typed_chunk, [1.0])
        class Client:
            def scroll_page(self, collection, *, limit, offset=None):
                return [point], None

        with self.assertRaisesRegex(ValueError, "tenant"):
            run_audited_evaluation(
                AuditedIndexSession(Client(), "chunks", [typed_chunk]),
                [_answerable_case()],
                {"guide": {"content": DOC_CONTENT, "visibility": "public", "tenant_id": 1}},
                _manifest(),
                lambda question, case, context: ([RetrievedChunk(typed_chunk)], [], False),
                k=1, context_for_case=lambda case: AuthorizationContext(True, "evaluator", (), 0),
                authority=_authority_for([typed_chunk]),
            )
        self.assertEqual(self.answered, [])

    def test_audited_policy_rejects_boolean_classification(self):
        typed_chunk = replace(self.chunks[0], classification=True)
        point = chunk_to_point(typed_chunk, [1.0])
        class Client:
            def scroll_page(self, collection, *, limit, offset=None):
                return [point], None
        with self.assertRaisesRegex(ValueError, "classification"):
            run_audited_evaluation(
                AuditedIndexSession(Client(), "chunks", [typed_chunk]),
                [_answerable_case()], _documents(), _manifest(),
                lambda question, case, context: ([RetrievedChunk(typed_chunk)], [], False),
                k=1, context_for_case=lambda case: AuthorizationContext(
                    "public", "evaluator", (), 1
                ),
                authority=_authority_for([typed_chunk]),
            )

    def test_audited_context_rejects_boolean_clearance(self):
        with self.assertRaisesRegex(ValueError, "clearance"):
            run_audited_evaluation(
                self._session([self.points, self.points]),
                [_answerable_case()], _documents(), _manifest(), self.answer_fn,
                k=1, context_for_case=lambda case: AuthorizationContext(
                    "public", "evaluator", (), True
                ),
                authority=self.authority,
            )
        self.assertEqual(self.answered, [])

    def test_a_non_session_object_cannot_stand_in_for_the_audit(self):
        class FakeSession:
            def open(self):
                return None

            def close(self):
                return None

        with self.assertRaisesRegex(TypeError, "AuditedIndexSession"):
            run_audited_evaluation(
                FakeSession(), self.cases, _documents(), _manifest(), self.answer_fn, k=1,
                context_for_case=self.context_for_case, authority=self.authority,
            )
        self.assertEqual(self.answered, [])


if __name__ == "__main__":
    unittest.main()
