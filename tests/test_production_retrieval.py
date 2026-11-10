from __future__ import annotations

import json
import subprocess
import sys
import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.acl_authority import AclPolicy, CanonicalAclAuthority
from rag_hermes.retrieval import (
    CanonicalAclError,
    postfilter_candidates,
    retrieve_authorized_candidates,
    score_authorized_pairs,
)
from rag_hermes.reranker_budget import RerankerBudgetExceeded


class FakeTokenizer:
    def __init__(self, lengths):
        self.lengths = iter(lengths)
        self.calls = []

    def __call__(self, query, passage, **kwargs):
        self.calls.append((query, passage, kwargs))
        return {"input_ids": list(range(next(self.lengths)))}


class FakeReranker:
    def __init__(self):
        self.calls = []

    def compute_score(self, pairs, **kwargs):
        self.calls.append((pairs, kwargs))
        return [0.25 for _ in pairs]


class FakeQdrantClient:
    def __init__(self, points):
        self.points = points
        self.calls = []

    def query(self, collection, vector, *, query_filter, limit):
        self.calls.append((collection, vector, query_filter, limit))
        return self.points


class ProductionAclBarrierTests(unittest.TestCase):
    def setUp(self):
        self.context = AuthorizationContext("alpha", "alice", ("admins",), 2)
        self.authority = CanonicalAclAuthority(
            {
                "allowed": AclPolicy("alpha", "private", "alice", ("admins",), (), 2, 7),
                "revoked": AclPolicy("alpha", "private", "bob", (), (), 2, 8),
            }
        )

    def _candidate(self, document_id="allowed", acl_version=7, **overrides):
        payload = {
            "document_id": document_id, "acl_version": acl_version, "text": "ok",
            "tenant_id": "alpha", "visibility": "private", "owner_id": "alice",
            "classification": 2, "allowed_group_ids": ["admins"],
            "allowed_user_ids": [], "tombstone": False,
        }
        payload.update(overrides)
        return {"payload": payload}

    def test_postfilter_uses_authority_and_rejects_revoked_or_stale_payload(self):
        candidates = [
            self._candidate(),
            self._candidate("revoked"),
            self._candidate("missing", 1),
        ]
        accepted, counters = postfilter_candidates(candidates, self.context, self.authority)
        self.assertEqual([item["payload"]["document_id"] for item in accepted], ["allowed"])
        self.assertEqual(counters.stale_acl_version, 1)
        self.assertEqual(counters.denied_by_authority, 1)

    def test_postfilter_does_not_accept_boolean_acl_version_as_integer(self):
        authority = CanonicalAclAuthority({
            "allowed": AclPolicy("alpha", "private", "alice", ("admins",), (), 2, 1),
        })
        candidates = [{"payload": {"document_id": "allowed", "acl_version": True}}]
        accepted, counters = postfilter_candidates(candidates, self.context, authority)
        self.assertEqual(accepted, [])
        self.assertEqual(counters.stale_acl_version, 1)

    def test_postfilter_does_not_coerce_document_identifier(self):
        authority = CanonicalAclAuthority({
            "1": AclPolicy("alpha", "private", "alice", ("admins",), (), 2, 7),
        })
        candidates = [{"payload": {"document_id": 1, "acl_version": 7}}]
        accepted, counters = postfilter_candidates(candidates, self.context, authority)
        self.assertEqual(accepted, [])
        self.assertEqual(counters.denied_by_authority, 1)

    def test_postfilter_fails_closed_on_index_acl_conflict(self):
        candidate = {"payload": {
            "document_id": "allowed", "acl_version": 7,
            "tenant_id": "alpha", "visibility": "private", "owner_id": "bob",
            "classification": 2, "allowed_group_ids": ["admins"],
            "allowed_user_ids": [], "tombstone": False,
        }}
        with self.assertRaisesRegex(PermissionError, "ACL payload conflicts"):
            postfilter_candidates([candidate], self.context, self.authority)

    def test_postfilter_rejects_every_acl_payload_conflict_and_missing_field(self):
        conflicts = (
            {"tenant_id": "foreign"}, {"visibility": "public"},
            {"classification": True}, {"allowed_group_ids": ["outsiders"]},
            {"allowed_user_ids": ["mallory"]}, {"tombstone": 0},
            {"owner_id": None}, {"allowed_group_ids": None},
        )
        for change in conflicts:
            with self.subTest(change=change):
                with self.assertRaises(CanonicalAclError):
                    postfilter_candidates(
                        [self._candidate(**change)], self.context, self.authority
                    )
        accepted, counters = postfilter_candidates(
            [self._candidate()], self.context, self.authority
        )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(counters.accepted, 1)

    def test_postfilter_rejects_boolean_fields_in_canonical_policy(self):
        authority = CanonicalAclAuthority({
            "allowed": AclPolicy("alpha", "private", "alice", ("admins",), (), True, True),
        })
        candidate = self._candidate(acl_version=1, classification=1)
        with self.assertRaisesRegex(ValueError, "canonical ACL policy"):
            postfilter_candidates([candidate], self.context, authority)

    def test_gpu_candidate_has_complete_acl_payload_for_postfilter(self):
        from rag_hermes import retrieval
        from rag_hermes.ingestion import Document, chunk_document
        chunk = chunk_document(Document(
            document_id="allowed", content="evidence", tenant_id="alpha",
            visibility="private", owner_id="alice", allowed_groups=("admins",),
            allowed_users=(), classification=2, doc_version=1,
            source_uri="synthetic://allowed", acl_version=7,
        ))[0]
        self.assertTrue(hasattr(retrieval, "acl_candidate_from_chunk"))
        candidate = retrieval.acl_candidate_from_chunk(chunk, 3)
        accepted, counters = postfilter_candidates([candidate], self.context, self.authority)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["payload"]["chunk_index"], 3)
        self.assertEqual(counters.accepted, 1)

    def test_gpu_runner_uses_complete_acl_candidate(self):
        from pathlib import Path
        runner = Path("scripts/run_bge_gpu_smoke.py").read_text(encoding="utf-8")
        self.assertIn("acl_candidate_from_chunk(chunks[index], index)", runner)

    def test_matrix_query_applies_qdrant_filter_then_canonical_authority(self):
        client = FakeQdrantClient([
            self._candidate(),
            self._candidate("revoked"),
        ])
        accepted, counters = retrieve_authorized_candidates(
            client,
            "chunks",
            [1.0, 0.0],
            context=self.context,
            authority=self.authority,
            limit=20,
        )
        self.assertEqual([item["payload"]["document_id"] for item in accepted], ["allowed"])
        self.assertEqual(counters.stale_acl_version, 1)
        self.assertEqual(client.calls[0][0], "chunks")
        self.assertIsNotNone(client.calls[0][2])

    def test_budget_check_is_immediately_before_compute_score(self):
        tokenizer = FakeTokenizer([5, 6])
        reranker = FakeReranker()
        candidates = [
            {"payload": {"text": "one", "document_id": "a"}},
            {"payload": {"text": "two", "document_id": "b"}},
        ]
        scores, counters = score_authorized_pairs(
            reranker, tokenizer, "q", candidates, max_length=6, batch_size=2
        )
        self.assertEqual(scores, [0.25, 0.25])
        self.assertEqual(counters.checked_pairs, 2)
        self.assertEqual(counters.maximum_pair_tokens, 6)
        self.assertEqual(reranker.calls[0][1]["max_length"], 6)
        self.assertFalse(tokenizer.calls[0][2]["truncation"])

    def test_reranker_rejects_wrong_score_cardinality(self):
        candidates = [
            {"payload": {"text": "one", "document_id": "a"}},
            {"payload": {"text": "two", "document_id": "b"}},
        ]
        for raw_scores in (0.9, [0.9], [0.9, 0.8, 0.7]):
            with self.subTest(raw_scores=raw_scores):
                tokenizer = FakeTokenizer([5, 6])

                class WrongCardinalityReranker:
                    def compute_score(self, pairs, **kwargs):
                        return raw_scores

                with self.assertRaisesRegex(ValueError, "one finite score per pair"):
                    score_authorized_pairs(
                        WrongCardinalityReranker(),
                        tokenizer,
                        "q",
                        candidates,
                        max_length=6,
                        batch_size=2,
                    )

    def test_reranker_rejects_non_finite_scores(self):
        for raw_score in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(raw_score=raw_score):
                tokenizer = FakeTokenizer([5])

                class NonFiniteReranker:
                    def compute_score(self, pairs, **kwargs):
                        return [raw_score]

                with self.assertRaisesRegex(ValueError, "one finite score per pair"):
                    score_authorized_pairs(
                        NonFiniteReranker(),
                        tokenizer,
                        "q",
                        [{"payload": {"text": "one", "document_id": "a"}}],
                        max_length=6,
                        batch_size=1,
                    )

    def test_over_budget_raises_before_compute_score(self):
        tokenizer = FakeTokenizer([7])
        reranker = FakeReranker()
        with self.assertRaises(RerankerBudgetExceeded):
            score_authorized_pairs(
                reranker,
                tokenizer,
                "q",
                [{"payload": {"text": "too long", "document_id": "x"}}],
                max_length=6,
                batch_size=1,
            )
        self.assertEqual(reranker.calls, [])

    def test_budget_guard_survives_python_optimized_mode(self):
        code = """
import json
from rag_hermes.retrieval import score_authorized_pairs
class T:
 def __call__(self, q, p, **kw): return {'input_ids': list(range(513))}
class R:
 def compute_score(self, pairs, **kw): raise RuntimeError('compute_score must not run')
try:
 score_authorized_pairs(R(), T(), 'q', [{'payload': {'text':'p','document_id':'x'}}], max_length=512, batch_size=1)
except Exception as exc:
 print(json.dumps({'type': type(exc).__name__, 'message': str(exc)}))
else:
 raise SystemExit(9)
"""
        result = subprocess.run(
            [sys.executable, "-O", "-c", code], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["type"], "RerankerBudgetExceeded")


if __name__ == "__main__":
    unittest.main()
