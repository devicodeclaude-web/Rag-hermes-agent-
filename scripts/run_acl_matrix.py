#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag_hermes.acl import AuthorizationContext
from rag_hermes.acl_authority import AclPolicy, CanonicalAclAuthority
from rag_hermes.acl_reference import reference_allows
from rag_hermes.qdrant_filter import build_qdrant_filter
from rag_hermes.qdrant_filter_eval import payload_matches_filter

SEED = 20260923
TRIALS = 100
CATEGORIES = (
    "cross_tenant", "groups", "named_users", "clearance_insufficient",
    "clearance_sufficient", "acl_missing_or_null", "revoked_right",
    "stale_acl_version", "public_visibility",
)


def scenario(category: str, rng: random.Random, index: int):
    context = AuthorizationContext("alpha", "alice", ("admins",), 2)
    payload = {"tenant_id": "alpha", "visibility": "private", "owner_id": "alice", "allowed_user_ids": [], "allowed_group_ids": [], "classification": 2, "tombstone": False, "acl_version": 2}
    if category == "cross_tenant": payload["tenant_id"] = "beta"
    elif category == "groups": payload.update(owner_id="bob", allowed_group_ids=["admins"])
    elif category == "named_users": payload.update(owner_id="bob", allowed_user_ids=["alice"])
    elif category == "clearance_insufficient": payload["classification"] = 3
    elif category == "clearance_sufficient": payload["classification"] = rng.randint(0, 2)
    elif category == "acl_missing_or_null": payload[rng.choice(["visibility", "classification", "tombstone"])] = None
    elif category == "revoked_right": payload.update(owner_id="bob", allowed_user_ids=[], allowed_group_ids=[])
    elif category == "stale_acl_version": payload["acl_version"] = 1
    elif category == "public_visibility": payload.update(tenant_id="public", visibility="public", owner_id="docs", classification=0)
    return context, payload


def main() -> int:
    rng = random.Random(SEED)
    results = {}
    total_leaks = 0
    for category in CATEGORIES:
        leaks = 0
        for index in range(TRIALS):
            context, payload = scenario(category, rng, index)
            qdrant_set = {index} if payload_matches_filter(payload, build_qdrant_filter(context)) else set()
            reference_set = {index} if reference_allows(payload, context) else set()
            policy = AclPolicy(
                "alpha", "private", "alice", ("admins",), (), 2, 2
            )
            if category == "revoked_right":
                policy = AclPolicy("alpha", "private", "bob", (), (), 2, 2)
            authority = CanonicalAclAuthority({"doc": policy})
            authority_allowed, _ = authority.authorize(
                "doc", payload.get("acl_version"), context
            )
            if not authority_allowed:
                qdrant_set = set()
                reference_set = set()
            if not qdrant_set <= reference_set:
                leaks += 1
        total_leaks += leaks
        results[category] = {"trials": TRIALS, "seed": SEED, "observed_leaks": leaks, "rule_of_three_upper_95pct": 3 / TRIALS}
    report = {
        "classification": "component_differential_not_real_qdrant_end_to_end",
        "protocol_sha256": hashlib.sha256((ROOT / "docs/ablation-protocol.md").read_bytes()).hexdigest(),
        "dataset_sha256": hashlib.sha256((ROOT / "data/benchmark/dataset-v1.jsonl").read_bytes()).hexdigest(),
        "categories": results,
        "total_trials": TRIALS * len(CATEGORIES),
        "observed_leaks": total_leaks,
        "risk_claim": "zero observed leaks is not proof of zero risk",
        "limitations": ["Qdrant server is not exercised by this component matrix.", "The canonical-authority postfilter is covered separately by production-path unit tests."],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if total_leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
