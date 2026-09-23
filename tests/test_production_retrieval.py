from __future__ import annotations

import json
import subprocess
import sys
import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.acl_authority import AclPolicy, CanonicalAclAuthority
from rag_hermes.retrieval import postfilter_candidates, score_authorized_pairs
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


class ProductionAclBarrierTests(unittest.TestCase):
    def setUp(self):
        self.context = AuthorizationContext("alpha", "alice", ("admins",), 2)
        self.authority = CanonicalAclAuthority(
            {
                "allowed": AclPolicy("alpha", "private", "alice", ("admins",), (), 2, 7),
                "revoked": AclPolicy("alpha", "private", "bob", (), (), 2, 8),
            }
        )

    def test_postfilter_uses_authority_and_rejects_revoked_or_stale_payload(self):
        candidates = [
            {"payload": {"document_id": "allowed", "acl_version": 7, "text": "ok"}},
            {"payload": {"document_id": "revoked", "acl_version": 7, "text": "stale"}},
            {"payload": {"document_id": "missing", "acl_version": 1, "text": "unknown"}},
        ]
        accepted, counters = postfilter_candidates(candidates, self.context, self.authority)
        self.assertEqual([item["payload"]["document_id"] for item in accepted], ["allowed"])
        self.assertEqual(counters.stale_acl_version, 1)
        self.assertEqual(counters.denied_by_authority, 1)

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
