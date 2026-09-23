#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import uuid
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag_hermes.acl_authority import CanonicalAclAuthority
from rag_hermes.acl_matrix import CATEGORIES, build_scenario
from rag_hermes.acl_reference import reference_allows
from rag_hermes.qdrant_filter import build_qdrant_filter
from rag_hermes.qdrant_rest import QdrantRestClient
from rag_hermes.qdrant_store import deterministic_test_vector
from rag_hermes.retrieval import retrieve_authorized_candidates

SEED = 20260923
TRIALS = 100
DIMENSIONS = 8
DEFAULT_OUTPUT = ROOT / "data/results/acl_matrix_qdrant.json"


class AclLeakDetected(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qdrant_identity(base_url: str) -> dict:
    with urlopen(base_url.rstrip("/") + "/", timeout=10) as response:
        return json.loads(response.read())


def run_category(client: QdrantRestClient, category: str, rng: random.Random) -> dict:
    collection = f"acl_matrix_{category}_{uuid.uuid4().hex[:10]}"
    scenarios = [build_scenario(category, index, rng) for index in range(TRIALS)]
    authority = CanonicalAclAuthority({
        item.payload["document_id"]: item.authority_policy for item in scenarios
    })
    failures: list[dict] = []
    pre_candidate_count = production_candidate_count = 0
    try:
        client.create_collection(collection, vector_size=DIMENSIONS)
        specification = json.loads((ROOT / "qdrant/payload-indexes.json").read_text(encoding="utf-8"))
        for index in specification["payload_indexes"]:
            client.create_payload_index(
                collection, index["field_name"], index["field_schema"]
            )
        points = []
        for trial, item in enumerate(scenarios):
            points.append({
                "id": trial,
                "vector": {"dense": deterministic_test_vector(item.payload["text"], dimensions=DIMENSIONS)},
                "payload": item.payload,
            })
        client.upsert(collection, points)

        for trial, item in enumerate(scenarios):
            vector = deterministic_test_vector(item.payload["text"], dimensions=DIMENSIONS)
            pre = client.query(
                collection,
                vector,
                query_filter=build_qdrant_filter(item.context),
                limit=TRIALS,
            )
            qdrant_ids = {point["payload"]["document_id"] for point in pre}
            reference_ids = {
                candidate.payload["document_id"]
                for candidate in scenarios
                if reference_allows(candidate.payload, item.context)
            }
            pre_candidate_count += len(qdrant_ids)
            if not qdrant_ids <= reference_ids:
                failure = {
                    "trial": trial,
                    "stage": "qdrant_prefilter",
                    "unexpected_document_ids": sorted(qdrant_ids - reference_ids),
                }
                failures.append(failure)
                raise AclLeakDetected(json.dumps(failure, sort_keys=True))

            production, counters = retrieve_authorized_candidates(
                client,
                collection,
                vector,
                context=item.context,
                authority=authority,
                limit=TRIALS,
            )
            production_ids = {point["payload"]["document_id"] for point in production}
            canonical_ids = set()
            for candidate in scenarios:
                document_id = candidate.payload["document_id"]
                allowed, _ = authority.authorize(
                    document_id,
                    candidate.payload.get("acl_version"),
                    item.context,
                )
                if reference_allows(candidate.payload, item.context) and allowed:
                    canonical_ids.add(document_id)
            production_candidate_count += len(production_ids)
            if not production_ids <= canonical_ids:
                failure = {
                    "trial": trial,
                    "stage": "canonical_postfilter",
                    "unexpected_document_ids": sorted(production_ids - canonical_ids),
                }
                failures.append(failure)
                raise AclLeakDetected(json.dumps(failure, sort_keys=True))

            target_id = item.payload["document_id"]
            expected_target = item.index_reference_allows and item.authority_allows
            if (target_id in production_ids) != expected_target:
                failure = {
                    "trial": trial,
                    "stage": "expected_target_visibility",
                    "target": target_id,
                    "expected_visible": expected_target,
                    "actual_visible": target_id in production_ids,
                    "barrier_counters": counters.__dict__,
                }
                failures.append(failure)
                raise AclLeakDetected(json.dumps(failure, sort_keys=True))
    finally:
        try:
            client.delete_collection(collection)
        except Exception as cleanup_error:
            failures.append({"stage": "cleanup", "error": repr(cleanup_error)})

    return {
        "trials": TRIALS,
        "seed": SEED,
        "observed_leaks": sum(
            item.get("stage") in {"qdrant_prefilter", "canonical_postfilter"}
            for item in failures
        ),
        "rule_of_three_upper_95pct": 3 / TRIALS,
        "qdrant_candidates_total": pre_candidate_count,
        "production_candidates_total": production_candidate_count,
        "failures": failures,
        "status": "FERMÉ" if not failures else "BLOQUÉ",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_INTEGRATION_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    output = Path(args.output)
    report = {
        "audited_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "real_qdrant_production_query_path_component_security_experiment",
        "qdrant": None,
        "seed": SEED,
        "trials_per_category": TRIALS,
        "protocol_sha256": sha256(ROOT / "docs/ablation-protocol.md"),
        "dataset_sha256": sha256(ROOT / "data/benchmark/dataset-v1.jsonl"),
        "authority": "CanonicalAclAuthority in-memory registry built from Document ACL metadata; no PostgreSQL authority exists",
        "categories": {},
        "failures": [],
        "limitations": [
            "This exercises local Qdrant and the production query plus canonical postfilter path, not a deployed service.",
            "Zero observed leaks is not proof of zero risk; each category reports the rule-of-three upper bound.",
            "The canonical authority is an in-memory registry, not a persistent external authority.",
            "No GPU, CUDA runtime, reranker model load, or A40 pod is exercised.",
        ],
    }
    exit_code = 0
    try:
        report["qdrant"] = qdrant_identity(args.qdrant_url)
        client = QdrantRestClient(args.qdrant_url)
        rng = random.Random(SEED)
        for category in CATEGORIES:
            report["categories"][category] = run_category(client, category, rng)
    except Exception as error:
        exit_code = 1
        report["failures"].append({"type": type(error).__name__, "message": str(error)})
    report["observed_leaks"] = sum(
        item.get("observed_leaks", 0) for item in report["categories"].values()
    )
    report["status"] = "FERMÉ" if exit_code == 0 and not report["failures"] else "BLOQUÉ"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
