"""Verifie le stratum contradiction (fichier dedie) et la realite des contradictions.

data/benchmark/dataset-v2-contradiction.jsonl vit hors de dataset-v2.jsonl
(public-only). Convention de verite-terrain : abstention sur contradiction
symetrique (no_answer) ; chaque paire a un controle positif (simple). Ce test
garde la structure ET verifie, au niveau des fixtures, que les deux docs d'une
paire se contredisent reellement (meme cle de fait, valeurs distinctes, chaque
valeur presente dans son contenu).
"""
from __future__ import annotations

import json
import unittest
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/benchmark/dataset-v2-contradiction.jsonl"
FIXTURES = ROOT / "data/fixtures/contradiction_documents.jsonl"


def _load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


class ContradictionDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = _load(DATASET)
        cls.docs = {d["document_id"]: d for d in _load(FIXTURES)}
        cls.by_pair = defaultdict(list)
        for d in cls.docs.values():
            cls.by_pair[d["contradiction_pair"]].append(d)

    def test_counts(self):
        self.assertEqual(len(self.cases), 8)
        self.assertEqual(len({c["case_id"] for c in self.cases}), 8)
        self.assertEqual(
            dict(Counter(c["category"] for c in self.cases)),
            {"no_answer": 4, "simple": 4},
        )

    def test_fixtures_really_contradict(self):
        """Chaque paire : meme cle, valeurs distinctes, chaque valeur dans son contenu."""
        self.assertTrue(self.by_pair, "aucune paire de fixtures")
        for pair, members in self.by_pair.items():
            self.assertEqual(len(members), 2, f"paire {pair}: {len(members)} docs (2 attendus)")
            keys = {m["contested_fact_key"] for m in members}
            self.assertEqual(len(keys), 1, f"paire {pair}: cles de fait divergentes {keys}")
            values = [m["contested_fact_value"] for m in members]
            self.assertNotEqual(values[0], values[1], f"paire {pair}: valeurs identiques")
            for m in members:
                self.assertIn(
                    m["contested_fact_value"], m["content"],
                    f"{m['document_id']}: valeur contestee absente du contenu",
                )

    def test_abstain_cases(self):
        for c in (c for c in self.cases if c["pair_role"] == "abstain"):
            self.assertEqual(c["category"], "no_answer")
            self.assertTrue(c["should_abstain"])
            self.assertEqual(c["relevant_document_ids"], [])
            pair_ids = {d["document_id"] for d in self.by_pair[c["contradiction_pair"]]}
            self.assertEqual(
                set(c["distractor_document_ids"]), pair_ids,
                f"{c['case_id']}: les 2 docs contradictoires doivent etre en distracteurs",
            )

    def test_control_cases(self):
        for c in (c for c in self.cases if c["pair_role"] == "control"):
            self.assertEqual(c["category"], "simple")
            self.assertFalse(c["should_abstain"])
            self.assertEqual(len(c["relevant_document_ids"]), 1)
            gold = c["relevant_document_ids"][0]
            pair_ids = {d["document_id"] for d in self.by_pair[c["contradiction_pair"]]}
            self.assertIn(gold, pair_ids)
            # le distracteur = l'AUTRE doc de la paire (meme entite, ne repond pas)
            self.assertEqual(len(c["distractor_document_ids"]), 1)
            self.assertEqual(set(c["distractor_document_ids"]), pair_ids - {gold})

    def test_each_pair_has_one_abstain_one_control(self):
        roles = defaultdict(list)
        for c in self.cases:
            roles[c["contradiction_pair"]].append(c["pair_role"])
        for pair, rs in roles.items():
            self.assertEqual(sorted(rs), ["abstain", "control"], f"paire {pair}: roles {rs}")


if __name__ == "__main__":
    unittest.main()
