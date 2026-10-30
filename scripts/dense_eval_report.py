#!/usr/bin/env python3
"""Evaluate the reviewed HUMAN dataset through the PERSISTED Qdrant dense path.

This exercises the real persisted retrieval pipeline end to end: corpus chunks
are upserted into an ephemeral Qdrant collection, every case is answered by a
real vector (ANN) search with the server-side ACL prefilter, and the results are
scored with the same runner as the lexical report.

Honesty contract: the local embedder is a DETERMINISTIC test vector, NOT a
semantic embedding. The report therefore sets ``quality_eligible = false`` and
``retriever = "qdrant_deterministic_not_an_embedding"``. It proves the plumbing
(persist -> ANN -> ACL -> scoring), not semantic quality. A real embedding model
(BGE-M3) is only injected during a GPU smoke; that run would relabel the report.

The fail-closed publication discipline (invalidate stale outputs first, publish
checksum before report as the commit marker, verify SHA-256) is reused verbatim
from the audited lexical CLI.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_hermes.dense_report import run_dense_evaluation
from rag_hermes.eval_corpus import (
    DEFAULT_CORPUS,
    corpus_manifest,
    load_documents,
    sha256_of_file,
)
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_rest import QdrantRestClient
from rag_hermes.qdrant_store import deterministic_test_vector

# Reuse the audited fail-closed publication helpers from the lexical CLI.
from scripts.human_eval_report import (
    _git_revision,
    _invalidate,
    _publish_artifacts,
    _validate_paths,
    load_cases,
)

DATASET = ROOT / "data/benchmark/dataset-v2.jsonl"
RESULTS = ROOT / "data/results/dense-qdrant-eval-report.json"
CHECKSUM = ROOT / "data/results/dense-qdrant-eval-report.sha256"
INDEX_SPEC = ROOT / "qdrant/payload-indexes.json"

# Deterministic test vector dimension. Not a semantic embedding dimension.
_DENSE_DIM = 8


def _embed(text: str) -> list[float]:
    return deterministic_test_vector(text, dimensions=_DENSE_DIM)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--checksum", type=Path, default=CHECKSUM)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--minimum-score", type=float, default=0.05)
    return parser


def _recover_path_args(arguments: list[str]) -> argparse.Namespace:
    """Recover path values without a parser that can exit before invalidation."""
    recovered = argparse.Namespace(
        dataset=DATASET, corpus=DEFAULT_CORPUS, results=RESULTS, checksum=CHECKSUM
    )
    destinations = {
        "--dataset": "dataset",
        "--corpus": "corpus",
        "--results": "results",
        "--checksum": "checksum",
    }
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            break
        matched_equals = False
        for option, destination in destinations.items():
            prefix = option + "="
            if argument.startswith(prefix):
                value = argument[len(prefix):]
                if value:
                    setattr(recovered, destination, Path(value))
                matched_equals = True
                break
        if matched_equals:
            index += 1
            continue
        destination = destinations.get(argument)
        if (
            destination is not None
            and index + 1 < len(arguments)
            and not arguments[index + 1].startswith("--")
        ):
            setattr(recovered, destination, Path(arguments[index + 1]))
            index += 2
            continue
        index += 1
    return recovered


def _help_requested(arguments: list[str]) -> bool:
    for argument in arguments:
        if argument == "--":
            return False
        if argument in {"-h", "--help"}:
            return True
    return False


def _provision_collection(client: QdrantRestClient, collection: str) -> None:
    client.create_collection(collection, vector_size=_DENSE_DIM)
    specification = json.loads(INDEX_SPEC.read_text(encoding="utf-8"))
    for index in specification["payload_indexes"]:
        client.create_payload_index(
            collection, index["field_name"], index["field_schema"]
        )


def main() -> int:
    if _help_requested(sys.argv[1:]):
        _build_parser().parse_args()

    path_args = _recover_path_args(sys.argv[1:])
    outputs_safe = False
    try:
        _validate_paths(
            path_args.dataset,
            path_args.corpus,
            path_args.results,
            path_args.checksum,
        )
        outputs_safe = True
        _invalidate((path_args.results, path_args.checksum))
    except (OSError, ValueError) as exc:
        print(f"VIOLATION: {exc}", file=sys.stderr)
        return 1

    args = _build_parser().parse_args()

    # NOTE: stale outputs were already invalidated above (invalidate-before-
    # compute). Do NOT move strict arg parsing before that invalidation, or a
    # bad --qdrant-url could leave a stale report consumable.
    client = QdrantRestClient(args.qdrant_url)
    collection = "hermes_dense_eval_" + uuid.uuid4().hex[:12]
    collection_created = False
    try:
        cases = load_cases(args.dataset)
        documents = load_documents(args.corpus)
        manifest = corpus_manifest(args.corpus)
        code_revision, working_tree_dirty = _git_revision()

        _provision_collection(client, collection)
        collection_created = True
        repository = QdrantChunkRepository(
            client, collection=collection, embed=_embed
        )

        started = time.time()
        results = run_dense_evaluation(
            cases,
            documents,
            manifest,
            repository,
            k=args.k,
            minimum_score=args.minimum_score,
            limit=args.k,
        )
        elapsed = time.time() - started

        payload = {
            "schema_version": 1,
            "track": "dense",
            "question_provenance_counts": dict(
                sorted(Counter(case["question_provenance"] for case in cases).items())
            ),
            # Deterministic test vector: this run makes no semantic quality claim.
            "quality_eligible": False,
            "evidence_level": "persisted_pipeline_plumbing",
            "granularity": "passage_span_overlap",
            "retriever": "qdrant_deterministic_not_an_embedding",
            "generator": None,
            "embedding_model": None,
            "reranker": None,
            "tokenizer": None,
            "hardware": "local_cpu",
            "precision": None,
            "qdrant_exercised": True,
            "qdrant_version_pinned": "1.19.0",
            "dense_dimension": _DENSE_DIM,
            "k": args.k,
            "minimum_score": args.minimum_score,
            "cases_total": len(cases),
            "corpus_documents": len(documents),
            "source_revision": manifest["source_revision"],
            "corpus_manifest_sha": manifest["corpus_manifest_sha"],
            "dataset_sha256": sha256_of_file(args.dataset),
            "code_revision": code_revision,
            "working_tree_dirty": working_tree_dirty,
            "elapsed_seconds": round(elapsed, 2),
            "results": results,
            "limitations": [
                "Deterministic test vector, NOT a semantic embedding: no retrieval-quality claim.",
                "Proves the persisted dense pipeline (ingest -> Qdrant ANN -> ACL prefilter -> scoring) end to end.",
                "Public corpus only; no private-corpus or multitenant quality measurement here.",
                "A real embedding model (BGE-M3) is exercised only during a GPU smoke, which would relabel this report.",
                "Descriptive metrics only; no bootstrap confidence intervals.",
            ],
        }
        report_bytes = (
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(report_bytes).hexdigest()
        _publish_artifacts(
            args.results,
            report_bytes,
            args.checksum,
            (digest + "\n").encode("ascii"),
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        if outputs_safe:
            try:
                _invalidate((args.results, args.checksum))
            except OSError:
                pass
        print(f"VIOLATION: {exc}", file=sys.stderr)
        return 1
    finally:
        # Guaranteed teardown: never leave an ephemeral evaluation collection
        # behind, even if scoring or publication raised.
        if collection_created:
            try:
                client.delete_collection(collection)
            except RuntimeError:
                # Best-effort teardown. This runs in `finally` AFTER the real
                # outcome (return 0 / return 1) is decided, so swallowing a
                # teardown-only failure can never mask the actual error.
                pass


if __name__ == "__main__":
    raise SystemExit(main())
