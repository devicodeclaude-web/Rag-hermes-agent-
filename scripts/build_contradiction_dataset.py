#!/usr/bin/env python3
"""Genere le stratum contradiction (fichier DEDIE).

dataset-v2.jsonl reste public-only ; la categorie 'contradiction' n'est pas dans
les 5 autorisees. Ce lot vit donc dans data/benchmark/dataset-v2-contradiction.jsonl
et s'appuie sur des fixtures synthetiques PUBLIQUES
data/fixtures/contradiction_documents.jsonl (entites fictives -> aucune 3e source
autoritaire dans le corpus reel, donc contradiction SYMETRIQUE).

Convention de verite-terrain (choisie, non derivable du code) : sur une
contradiction SYMETRIQUE non resolue, le comportement attendu est l'ABSTENTION
(should_abstain=true, categorie no_answer). Chaque paire fournit aussi un CONTROLE
positif : une question sur un fait NON conteste, present dans un seul doc ->
answered (categorie simple). Le controle prouve que l'abstention vient du CONFLIT,
pas d'un evitement des documents.

Regles d'annotation : les deux docs contradictoires sont en distracteurs du cas
abstention (annotation du contexte conflictuel) ; ils NE DOIVENT PAS etre presentes
au generateur comme reponse. Metrique contradiction rapportee separement.

Garde-fous d'authoring (le script refuse d'ecrire sinon) : chaque paire a 2 docs,
meme contested_fact_key, 2 valeurs DISTINCTES, chaque valeur presente litteralement
dans son doc ; le fait de controle est present dans le doc A et absent du doc B.

Usage : PYTHONPATH=. /root/work/venv/bin/python scripts/build_contradiction_dataset.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data/fixtures/contradiction_documents.jsonl"
OUT = ROOT / "data/benchmark/dataset-v2-contradiction.jsonl"

# pair -> (abstain_question, control_question, control_fact_substring)
PLAN = {
    "halcyon": (
        "Quel est le delai d'expiration par defaut du connecteur Halcyon ?",
        "Dans quel fichier se configure le connecteur Halcyon ?",
        "halcyon.toml",
    ),
    "vermillon": (
        "Quelle est la taille maximale par defaut du cache Vermillon ?",
        "Quelle politique d'eviction le cache Vermillon applique-t-il ?",
        "LRU",
    ),
    "obsidienne": (
        "Quel est le port d'ecoute par defaut du pilote Obsidienne ?",
        "Quel protocole le pilote Obsidienne utilise-t-il pour communiquer ?",
        "gRPC",
    ),
    "tancrede": (
        "Quel est le nombre maximal de tentatives par defaut du greffon Tancrede ?",
        "Quelle strategie d'attente le greffon Tancrede applique-t-il entre les essais ?",
        "backoff exponentiel",
    ),
}

NOTE_ABSTAIN = (
    "Stratum contradiction (fixtures synthetiques publiques). Contradiction "
    "SYMETRIQUE : deux docs egalement autoritaires affirment des valeurs differentes "
    "pour le meme fait, aucune 3e source dans le corpus. Convention de verite-terrain : "
    "abstention attendue (statut terminal 'abstained'). Les deux docs sont en "
    "distracteurs (contexte conflictuel) ; ne JAMAIS les presenter comme reponse."
)
NOTE_CONTROL = (
    "Controle positif de la paire : fait NON conteste, present dans un seul doc -> "
    "answered. Prouve que l'abstention du cas jumeau vient du CONFLIT, pas d'un "
    "evitement des documents. L'autre doc de la paire (meme entite, ne repond pas) "
    "est le distracteur proche."
)


def load_fixtures() -> dict[str, dict]:
    docs = {}
    for line in FIXTURES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            docs[r["document_id"]] = r
    return docs


def main() -> int:
    docs = load_fixtures()
    by_pair: dict[str, list[dict]] = {}
    for r in docs.values():
        by_pair.setdefault(r["contradiction_pair"], []).append(r)

    rows = []
    n = 0
    for pair, (q_abstain, q_control, control_sub) in PLAN.items():
        members = sorted(by_pair.get(pair, []), key=lambda d: d["document_id"])
        if len(members) != 2:
            raise SystemExit(f"paire {pair}: {len(members)} docs (2 attendus)")
        a, b = members  # -a avant -b par tri d'id
        # --- garde-fous : la contradiction est reelle ---
        if a["contested_fact_key"] != b["contested_fact_key"]:
            raise SystemExit(f"paire {pair}: cles de fait differentes")
        if a["contested_fact_value"] == b["contested_fact_value"]:
            raise SystemExit(f"paire {pair}: valeurs identiques -> pas de contradiction")
        for d in (a, b):
            if d["contested_fact_value"] not in d["content"]:
                raise SystemExit(f"{d['document_id']}: valeur contestee absente du contenu")
        # --- garde-fous : le fait de controle est unique au doc A ---
        if control_sub not in a["content"]:
            raise SystemExit(f"paire {pair}: fait de controle absent du doc A")
        if control_sub in b["content"]:
            raise SystemExit(f"paire {pair}: fait de controle present dans B -> gold non unique")

        n += 1
        rows.append({
            "acl_probe": False,
            "authorship": "synthetic_contradiction_convention",
            "case_id": f"con-{n:03d}",
            "case_kind": "abstain_on_contradiction",
            "category": "no_answer",
            "contested_fact_key": a["contested_fact_key"],
            "contradiction_pair": pair,
            "decision_reference_status": "convention_symmetric_abstain",
            "distractor_document_ids": [a["document_id"], b["document_id"]],
            "distractor_miner": "handpicked_contradiction",
            "manual_review_status": "convention",
            "multi_hop": False,
            "pair_role": "abstain",
            "provenance_detail": "synthetic_symmetric_contradiction; ground_truth=convention_abstain",
            "question": q_abstain,
            "relevant_document_ids": [],
            "review_note": NOTE_ABSTAIN,
            "should_abstain": True,
        })
        n += 1
        rows.append({
            "acl_probe": False,
            "authorship": "synthetic_contradiction_convention",
            "case_id": f"con-{n:03d}",
            "case_kind": "consistency_control",
            "category": "simple",
            "contradiction_pair": pair,
            "decision_reference_status": "convention_consistency_control",
            "distractor_document_ids": [b["document_id"]],
            "distractor_miner": "handpicked_contradiction",
            "manual_review_status": "convention",
            "multi_hop": False,
            "pair_role": "control",
            "provenance_detail": "synthetic_uncontested_fact; ground_truth=answered",
            "question": q_control,
            "relevant_document_ids": [a["document_id"]],
            "review_note": NOTE_CONTROL,
            "should_abstain": False,
        })

    rows.sort(key=lambda r: r["case_id"])
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + "\n", encoding="utf-8")
    n_ab = sum(1 for r in rows if r["should_abstain"])
    print(f"ecrit : {OUT.relative_to(ROOT)} ({len(rows)} cas : {n_ab} no_answer / {len(rows) - n_ab} simple)")
    print("garde-fous contradiction + controle verifies ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
