#!/usr/bin/env python3
"""Genere le stratum acl_probe (corpus prive) dans un fichier DEDIE.

dataset-v2.jsonl reste public-only (invariantes de tests/test_dataset_qa.py :
acl_probe False partout, cibles disjointes des docs prives). Ce lot vit donc
dans data/benchmark/dataset-v2-acl-probe.jsonl.

Conception : 11 cas en PAIRES APPARIEES. Chaque cas negatif partage la question
MOT POUR MOT avec son controle positif ; seul le principal (tenant/user/groups/
clearance) change, isolant UNE condition ACL a la fois.

Verite-terrain DERIVEE mecaniquement : pour chaque cas, l'attente (should_abstain)
est verifiee ici contre rag_hermes.acl_authority.AclPolicy.allows() AVANT ecriture.
Le script refuse d'ecrire si une attente ne correspond pas a la politique reelle.
Le meme invariant est re-teste en CI par tests/test_acl_probe_dataset.py.

Regles d'annotation (validees) :
- Refus => relevant_document_ids=[] et le doc INTERDIT en distractor (annotation
  d'eval). Ce distracteur NE DOIT JAMAIS etre injecte dans le contexte du generateur.
- La metrique acl_probe est rapportee separement de la qualite de retrieval.

Usage : PYTHONPATH=. /root/work/venv/bin/python scripts/build_acl_probe_dataset.py
"""
from __future__ import annotations

import json
from pathlib import Path

from rag_hermes.acl import AuthorizationContext
from rag_hermes.acl_authority import AclPolicy
from rag_hermes.dataset import load_documents

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data/fixtures/private_and_synthetic_documents.jsonl"
OUT = ROOT / "data/benchmark/dataset-v2-acl-probe.jsonl"

# Enonces explicites, reutilises MOT POUR MOT entre chaque negatif et son positif.
Q_ALPHA = "Quelle est la balise de rotation du dossier confidentiel du tenant Alpha ?"
Q_BETA = "Quelle est la balise de rotation du dossier confidentiel du tenant Beta ?"
Q_GAMMA = "Quelle est la balise de rotation du dossier confidentiel du tenant Gamma ?"
Q_JARVIS = "Quel est le code de validation interne de la convention Jarvis du tenant personal ?"

# (case_id, question, target_doc, principal(tenant,user,groups,clearance),
#  should_abstain, acl_scenario, pair_group, pair_role)
SPEC = [
    ("acl-001", Q_ALPHA, "tenant-alpha-secret", ("alpha", "alice", ("admins",), 2), False, "owner", "alpha-balise", "positive"),
    ("acl-002", Q_BETA, "tenant-beta-secret", ("beta", "bob", ("admins",), 2), False, "owner", "beta-balise", "positive"),
    ("acl-003", Q_JARVIS, "jarvis-placeholder", ("personal", "user", ("owners",), 2), False, "owner", "jarvis-code", "positive"),
    ("acl-004", Q_GAMMA, "tenant-gamma-secret", ("gamma", "gina", ("admins",), 2), False, "owner", "gamma-balise", "positive"),
    ("acl-005", Q_ALPHA, "tenant-alpha-secret", ("alpha", "carol", ("admins",), 2), False, "group_grant", "alpha-group", "positive"),
    ("acl-006", Q_ALPHA, "tenant-alpha-secret", ("beta", "bob", ("admins",), 2), True, "cross_tenant", "alpha-balise", "negative"),
    ("acl-007", Q_BETA, "tenant-beta-secret", ("gamma", "gina", ("admins",), 2), True, "cross_tenant", "beta-balise", "negative"),
    ("acl-008", Q_JARVIS, "jarvis-placeholder", ("alpha", "alice", ("admins",), 2), True, "cross_tenant", "jarvis-code", "negative"),
    ("acl-009", Q_ALPHA, "tenant-alpha-secret", ("alpha", "carol", (), 2), True, "group_insufficient", "alpha-group", "negative"),
    ("acl-010", Q_ALPHA, "tenant-alpha-secret", ("alpha", "alice", ("admins",), 0), True, "clearance_insufficient", "alpha-balise", "negative"),
    ("acl-011", Q_GAMMA, "tenant-gamma-secret", ("public", "evaluator", (), 2), True, "public_tenant_cross", "gamma-balise", "negative"),
]

REVIEW_NOTE = (
    "Cas synthetique acl_probe (corpus prive). Verite-terrain DERIVEE mecaniquement "
    "de rag_hermes.acl_authority.AclPolicy.allows() ; re-verifiee en CI par "
    "tests/test_acl_probe_dataset.py. Pas de revue humaine requise : l'attente est "
    "prouvable contre le code d'enforcement. Refus => relevant=[] et doc interdit en "
    "distracteur (annotation d'eval, NE JAMAIS injecter dans le contexte du generateur)."
)


def main() -> int:
    docs = {d.document_id: d for d in load_documents(FIXTURES)}
    policies = {
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

    rows = []
    for (cid, q, target, principal, should_abstain, scenario, pair, role) in SPEC:
        tenant, user, groups, clearance = principal
        ctx = AuthorizationContext(tenant_id=tenant, user_id=user, groups=tuple(groups), clearance=clearance)
        allowed = policies[target].allows(ctx)
        # Invariant d'authoring : l'attente DOIT correspondre a la politique reelle.
        if allowed == should_abstain:
            raise SystemExit(
                f"{cid}: INCOHERENT avec AclPolicy — allows={allowed} mais should_abstain={should_abstain} "
                f"(target={target}, principal={principal})"
            )
        rows.append({
            "acl_probe": True,
            "acl_scenario": scenario,
            "authorship": "synthetic_acl_probe_policy_derived",
            "case_id": cid,
            "category": "no_answer" if should_abstain else "simple",
            "clearance": clearance,
            "decision_reference_status": "policy_derived",
            "distractor_document_ids": [target] if should_abstain else [],
            "distractor_miner": "handpicked_acl_probe",
            "groups": list(groups),
            "manual_review_status": "policy_derived",
            "multi_hop": False,
            "pair_group": pair,
            "pair_role": role,
            "provenance_detail": "synthetic_fixture_principal; ground_truth=AclPolicy.allows",
            "question": q,
            "relevant_document_ids": [] if should_abstain else [target],
            "review_note": REVIEW_NOTE,
            "should_abstain": should_abstain,
            "tenant_id": tenant,
            "user_id": user,
        })

    rows.sort(key=lambda r: r["case_id"])
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + "\n", encoding="utf-8")
    n_pos = sum(1 for r in rows if not r["should_abstain"])
    n_neg = len(rows) - n_pos
    print(f"ecrit : {OUT.relative_to(ROOT)} ({len(rows)} cas : {n_pos} simple / {n_neg} no_answer)")
    print("toutes les attentes verifiees contre AclPolicy.allows() ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
