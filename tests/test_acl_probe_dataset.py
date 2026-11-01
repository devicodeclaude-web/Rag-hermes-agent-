"""Verifie le stratum acl_probe (corpus prive) contre la politique reelle.

Le fichier data/benchmark/dataset-v2-acl-probe.jsonl est un lot DEDIE (il ne vit
PAS dans dataset-v2.jsonl, qui reste public-only). La verite-terrain de chaque cas
(should_abstain) doit correspondre EXACTEMENT a rag_hermes.acl_authority.AclPolicy
.allows() appliquee au principal du cas et au doc cible. Ce test est le garde CI
qui empeche le lot de deriver du comportement d'enforcement reel.
"""
from __future__ import annotations

import json
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from rag_hermes.acl import AuthorizationContext
from rag_hermes.acl_authority import AclPolicy
from rag_hermes.dataset import load_documents

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/benchmark/dataset-v2-acl-probe.jsonl"
FIXTURES = ROOT / "data/fixtures/private_and_synthetic_documents.jsonl"

PRINCIPAL_FIELDS = {"tenant_id", "user_id", "groups", "clearance", "should_abstain", "acl_probe"}


def _load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


class AclProbeDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = _load(DATASET)
        docs = {d.document_id: d for d in load_documents(FIXTURES)}
        cls.private_ids = set(docs)
        cls.policies = {
            did: AclPolicy(
                tenant_id=d.tenant_id,
                visibility=d.visibility,
                owner_id=d.owner_id,
                allowed_groups=d.allowed_groups,
                allowed_users=d.allowed_users,
                classification=d.classification,
                acl_version=d.acl_version,
            )
            for did, d in docs.items()
        }

    def test_counts_and_unique_ids(self):
        self.assertEqual(len(self.cases), 11)
        self.assertEqual(len({c["case_id"] for c in self.cases}), 11)
        self.assertEqual(
            dict(Counter(c["category"] for c in self.cases)),
            {"simple": 5, "no_answer": 6},
        )

    def test_structure_and_flags(self):
        for c in self.cases:
            self.assertTrue(PRINCIPAL_FIELDS <= set(c), f"{c['case_id']}: champs principal manquants")
            self.assertIs(c["acl_probe"], True, f"{c['case_id']}: acl_probe doit etre True")
            self.assertIsInstance(c["should_abstain"], bool)
            # mapping categorie <-> abstention
            expected_cat = "no_answer" if c["should_abstain"] else "simple"
            self.assertEqual(c["category"], expected_cat, f"{c['case_id']}: categorie incoherente")
            if c["should_abstain"]:
                self.assertEqual(c["relevant_document_ids"], [], f"{c['case_id']}: refus => relevant vide")
                self.assertEqual(len(c["distractor_document_ids"]), 1, f"{c['case_id']}: refus => 1 doc interdit en distracteur")
                target = c["distractor_document_ids"][0]
            else:
                self.assertEqual(len(c["relevant_document_ids"]), 1, f"{c['case_id']}: acces => 1 doc cible")
                self.assertEqual(c["distractor_document_ids"], [], f"{c['case_id']}: acces => pas de distracteur")
                target = c["relevant_document_ids"][0]
            self.assertIn(target, self.private_ids, f"{c['case_id']}: la cible doit etre un doc prive")

    def test_ground_truth_matches_acl_policy(self):
        """Coeur du garde : should_abstain == NOT AclPolicy.allows(principal)."""
        for c in self.cases:
            target = (c["distractor_document_ids"] or c["relevant_document_ids"])[0]
            ctx = AuthorizationContext(
                tenant_id=c["tenant_id"],
                user_id=c["user_id"],
                groups=tuple(c["groups"]),
                clearance=int(c["clearance"]),
            )
            allowed = self.policies[target].allows(ctx)
            self.assertEqual(
                allowed,
                not c["should_abstain"],
                f"{c['case_id']}: AclPolicy.allows={allowed} mais should_abstain={c['should_abstain']}",
            )

    def test_matched_pairs_share_question_verbatim(self):
        """Dans chaque pair_group, tous les cas partagent l'enonce MOT POUR MOT."""
        groups = defaultdict(list)
        for c in self.cases:
            groups[c["pair_group"]].append(c)
        saw_pos_and_neg = 0
        for pair, members in groups.items():
            questions = {m["question"] for m in members}
            self.assertEqual(len(questions), 1, f"pair {pair}: enonces divergents {questions}")
            roles = {m["pair_role"] for m in members}
            if {"positive", "negative"} <= roles:
                saw_pos_and_neg += 1
        # au moins les paires isolant groupe / clearance / cross-tenant
        self.assertGreaterEqual(saw_pos_and_neg, 3)

    def test_isolation_pairs_change_one_condition(self):
        by_id = {c["case_id"]: c for c in self.cases}
        # A1 vs C2 : seule la clearance change (meme user alice, meme groups)
        a1, c2 = by_id["acl-001"], by_id["acl-010"]
        self.assertEqual(a1["question"], c2["question"])
        self.assertEqual((a1["tenant_id"], a1["user_id"], a1["groups"]), (c2["tenant_id"], c2["user_id"], c2["groups"]))
        self.assertNotEqual(a1["clearance"], c2["clearance"])
        # A5 vs C1 : seuls les groups changent (meme user carol, meme clearance)
        a5, c1 = by_id["acl-005"], by_id["acl-009"]
        self.assertEqual(a5["question"], c1["question"])
        self.assertEqual((a5["tenant_id"], a5["user_id"], a5["clearance"]), (c1["tenant_id"], c1["user_id"], c1["clearance"]))
        self.assertNotEqual(a5["groups"], c1["groups"])


if __name__ == "__main__":
    unittest.main()
