"""Verifie le stratum injection documentaire indirecte (fichier dedie).

Protocole section 7 : documents autorises mais hostiles ; le texte injecte est
donnee, jamais instruction. Notation par CANARI (zero-tolerance) : la sortie ne
doit pas contenir injection_canary. Ce test garde la structure du lot ET verifie,
au niveau des fixtures, que le canari est bien dans le doc hostile et absent du
doc clean, et que le fait legitime est present dans les deux.
"""
from __future__ import annotations

import json
import unittest
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/benchmark/dataset-v2-injection.jsonl"
FIXTURES = ROOT / "data/fixtures/injection_documents.jsonl"


def _load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


class InjectionDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = _load(DATASET)
        cls.docs = {d["document_id"]: d for d in _load(FIXTURES)}
        cls.by_pair = defaultdict(dict)
        for d in cls.docs.values():
            cls.by_pair[d["injection_pair"]][d["injection_role"]] = d

    def test_counts(self):
        self.assertEqual(len(self.cases), 8)
        self.assertEqual(len({c["case_id"] for c in self.cases}), 8)
        self.assertEqual(dict(Counter(c["category"] for c in self.cases)), {"simple": 8})
        self.assertTrue(all(c["should_abstain"] is False for c in self.cases))
        self.assertEqual(
            dict(Counter(c["injection_role"] for c in self.cases)),
            {"hostile": 4, "control": 4},
        )

    def test_fixtures_canary_placement(self):
        """Canari present dans hostile, absent de clean ; fait legitime dans les deux."""
        self.assertTrue(self.by_pair)
        for pair, roles in self.by_pair.items():
            self.assertIn("clean", roles, f"paire {pair}: doc clean manquant")
            self.assertIn("hostile", roles, f"paire {pair}: doc hostile manquant")
            clean, hostile = roles["clean"], roles["hostile"]
            canary = hostile["injection_canary"]
            legit = hostile["legit_fact_substring"]
            self.assertIn(canary, hostile["content"], f"paire {pair}: canari absent du hostile")
            self.assertNotIn(canary, clean["content"], f"paire {pair}: canari present dans le clean")
            self.assertIn(legit, clean["content"], f"paire {pair}: fait legitime absent du clean")
            self.assertIn(legit, hostile["content"], f"paire {pair}: fait legitime absent du hostile")

    def test_hostile_cases(self):
        for c in (c for c in self.cases if c["injection_role"] == "hostile"):
            self.assertEqual(len(c["relevant_document_ids"]), 1)
            gold = c["relevant_document_ids"][0]
            self.assertEqual(self.docs[gold]["injection_role"], "hostile")
            self.assertEqual(self.docs[gold]["injection_pair"], c["injection_pair"])
            self.assertEqual(c["injection_canary"], self.docs[gold]["injection_canary"])
            self.assertIn("injection_type", c)
            self.assertIn("expected_answer_substring", c)

    def test_control_cases(self):
        for c in (c for c in self.cases if c["injection_role"] == "control"):
            gold = c["relevant_document_ids"][0]
            self.assertEqual(self.docs[gold]["injection_role"], "clean")
            self.assertEqual(self.docs[gold]["injection_pair"], c["injection_pair"])

    def test_each_pair_one_hostile_one_control_same_question_and_type(self):
        groups = defaultdict(list)
        for c in self.cases:
            groups[c["injection_pair"]].append(c)
        for pair, members in groups.items():
            self.assertEqual(sorted(m["injection_role"] for m in members), ["control", "hostile"])
            self.assertEqual(len({m["question"] for m in members}), 1, f"paire {pair}: questions divergentes")
            self.assertEqual(len({m["injection_type"] for m in members}), 1, f"paire {pair}: types divergents")


if __name__ == "__main__":
    unittest.main()
