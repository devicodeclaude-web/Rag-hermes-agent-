#!/usr/bin/env python3
"""Evaluate the reviewed HUMAN dataset with the local lexical baseline.

The report is descriptive component-level evidence, not a production-readiness
claim. EN->EN is the primary lexical baseline; FR->EN is diagnostic only.
Current outputs are invalidated before work and published atomically on success.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_hermes.eval_corpus import (
    DEFAULT_CORPUS,
    corpus_manifest,
    load_documents,
    sha256_of_file,
)
from rag_hermes.human_report import run_human_evaluation

DATASET = ROOT / "data/benchmark/dataset-v2.jsonl"
RESULTS = ROOT / "data/results/human-lexical-eval-report.json"
CHECKSUM = ROOT / "data/results/human-lexical-eval-report.sha256"


def load_cases(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _validate_paths(dataset: Path, corpus: Path, results: Path, checksum: Path) -> None:
    inputs = {_resolved(dataset), _resolved(corpus)}
    outputs = [_resolved(results), _resolved(checksum)]
    all_paths = (dataset, corpus, results, checksum)
    existing_alias = any(
        left.exists() and right.exists() and left.samefile(right)
        for index, left in enumerate(all_paths)
        for right in all_paths[index + 1 :]
    )
    if len(set(outputs)) != len(outputs) or any(output in inputs for output in outputs):
        raise ValueError("results and checksum paths must be distinct from inputs")
    if existing_alias:
        raise ValueError("existing input/output paths must not alias through links")


def _invalidate(outputs: tuple[Path, ...]) -> None:
    failures: list[OSError] = []
    marker = b'{"status":"INVALIDATED"}\n'
    for path in outputs:
        if not path.exists():
            continue
        try:
            # Replace stale success bytes before unlinking. If unlink fails, the
            # fixed output path remains explicitly non-consumable.
            _atomic_write(path, marker)
        except OSError as exc:
            failures.append(OSError(f"cannot mark output invalid: {path}"))
            continue
        try:
            path.unlink()
        except OSError as exc:
            failures.append(OSError(f"cannot remove invalidated output: {path}"))
    if failures:
        raise OSError("one or more outputs could not be fully invalidated") from failures[0]


def _git_revision() -> tuple[str, bool]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    )
    return revision, dirty


def _stage_bytes(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return temporary


def _atomic_write(path: Path, content: bytes) -> None:
    temporary: Path | None = None
    try:
        temporary = _stage_bytes(path, content)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _publish_artifacts(
    results: Path,
    report_bytes: bytes,
    checksum: Path,
    checksum_bytes: bytes,
) -> None:
    """Publish checksum first and report last as the commit marker.

    Consumers must require the report to exist and verify it against the
    checksum. An abrupt stop between renames can leave a checksum alone, never a
    newly committed report without its checksum.
    """
    report_temporary: Path | None = None
    checksum_temporary: Path | None = None
    try:
        checksum_temporary = _stage_bytes(checksum, checksum_bytes)
        report_temporary = _stage_bytes(results, report_bytes)
        os.replace(checksum_temporary, checksum)
        checksum_temporary = None
        os.replace(report_temporary, results)
        report_temporary = None
    finally:
        for temporary in (report_temporary, checksum_temporary):
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--checksum", type=Path, default=CHECKSUM)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--minimum-score", type=float, default=0.05)
    return parser


def _recover_path_args(arguments: list[str]) -> argparse.Namespace:
    """Recover path values without a parser that can exit before invalidation."""
    recovered = argparse.Namespace(
        dataset=DATASET,
        corpus=DEFAULT_CORPUS,
        results=RESULTS,
        checksum=CHECKSUM,
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
                value = argument[len(prefix) :]
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


def main() -> int:
    # Help is side-effect free only when it occurs before argparse's ``--``
    # option terminator. After that separator it is ordinary invalid input and
    # stale outputs must be invalidated before strict parsing fails.
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

    # Invalid typed arguments now exit non-zero only after stale outputs have
    # been removed. argparse's SystemExit intentionally remains unmodified.
    args = _build_parser().parse_args()

    try:
        cases = load_cases(args.dataset)
        documents = load_documents(args.corpus)
        manifest = corpus_manifest(args.corpus)
        code_revision, working_tree_dirty = _git_revision()

        started = time.time()
        results = run_human_evaluation(
            cases,
            documents,
            manifest,
            k=args.k,
            minimum_score=args.minimum_score,
        )
        elapsed = time.time() - started

        payload = {
            "schema_version": 1,
            "track": "human",
            "question_provenance_counts": dict(
                sorted(Counter(case["question_provenance"] for case in cases).items())
            ),
            "quality_eligible": True,
            "evidence_level": "component_integration",
            "granularity": "passage_span_overlap",
            "retriever": "in_memory_lexical_baseline",
            "generator": None,
            "embedding_model": None,
            "reranker": None,
            "tokenizer": None,
            "hardware": "local_cpu",
            "precision": None,
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
                "Descriptive metrics only; no bootstrap confidence intervals in this report.",
                "FR->EN lexical scores are diagnostic only and not an equitable cross-lingual baseline.",
                "No dense embeddings, reranker, generator, private corpus, or production deployment is exercised.",
                "Citation support is span-overlap retrieval evidence, not a human judgment of generated claims.",
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
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        # Outputs were invalidated before input loading/computation. Remove any
        # partially published current artifact while preserving every input.
        if outputs_safe:
            try:
                _invalidate((args.results, args.checksum))
            except OSError:
                # _invalidate replaces any writable target with an explicit
                # marker before unlinking, so an unlink failure is non-consumable.
                pass
        print(f"VIOLATION: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
