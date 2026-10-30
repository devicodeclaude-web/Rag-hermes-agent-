#!/usr/bin/env python3
"""Compare the RAG answer path against the closed-book baseline, offline.

Produces two artefacts from the synthetic track:
  - data/results/campaign-comparison.json : abstention metrics for BOTH campaigns;
  - data/results/campaign-review-sample.jsonl : the >=20% human-review sample,
    each line pairing a question with its RAG answer and closed-book answer plus
    empty verdict fields for a human to fill.

HONESTY / OFFLINE LIMIT: with no LLM endpoint wired in, the RAG side uses the
extractive RagService answer (top authorized chunk text) and the closed-book side
abstains by default (it has nothing to answer from). The abstention axis is real;
answer CORRECTNESS is left to the human review — no offline metric can score it.
When RAG_GENERATOR_* / a real baseline endpoint are provided, swap the injected
answer callables for the networked generators.

Exit codes: 0 on success, 1 on any violation (e.g. stale corpus hash).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import asdict

from rag_hermes.acl import AuthorizationContext
import os

from rag_hermes.app_factory import build_baseline_generator
from rag_hermes.campaign_compare import compare_campaigns
from rag_hermes.closed_book import CLOSED_BOOK_ABSTENTION
from rag_hermes.eval_corpus import DEFAULT_CORPUS, corpus_manifest, load_documents
from rag_hermes.evaluation_dataset import is_quality_eligible
from rag_hermes.generator import (
    ABSTENTION_ANSWER as RAG_ABSTENTION,
    GenerationError,
)
from rag_hermes.synthetic_report import build_public_service

DATASET = ROOT / "data/benchmark/dataset-synthetic.jsonl"
REPORT = ROOT / "data/results/campaign-comparison.json"
REVIEW = ROOT / "data/results/campaign-review-sample.jsonl"


def load_cases(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _invalidate_outputs(paths: tuple[Path, ...]) -> None:
    failures: list[OSError] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            path.write_text('{"status":"INVALIDATED"}\n', encoding="utf-8")
        except OSError as exc:
            failures.append(exc)
        try:
            path.unlink()
        except OSError as exc:
            failures.append(exc)
    if failures:
        raise OSError("campaign artifact invalidation failed")


def _staged_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.tmp.",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)


def _publish_artifacts(
    report_path: Path,
    report_content: str,
    review_path: Path,
    review_content: str,
) -> None:
    report_tmp: Path | None = None
    review_tmp: Path | None = None
    try:
        report_tmp = _staged_text(report_path, report_content)
        review_tmp = _staged_text(review_path, review_content)
        os.replace(review_tmp, review_path)
        review_tmp = None
        os.replace(report_tmp, report_path)
        report_tmp = None
    finally:
        for temporary in (report_tmp, review_tmp):
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--review", type=Path, default=REVIEW)
    parser.add_argument("--review-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--minimum-score", type=float, default=0.05)
    return parser


def _build_path_parser() -> argparse.ArgumentParser:
    # Tolerant parser used only to recover the artifact paths *before* strict
    # parsing. It must accept everything (add_help=False, parse_known_args) so
    # that even an invalid --seed/--minimum-score still lets us invalidate stale
    # outputs: a failed run must never leave a consumable, out-of-date report.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--review", type=Path, default=REVIEW)
    return parser


def main() -> int:
    # --help must exit before any side effect, so honour it first via the full
    # parser (argparse raises SystemExit on -h/--help before we touch disk).
    if any(argument in {"-h", "--help"} for argument in sys.argv[1:]):
        _build_parser().parse_args()

    # Recover artifact paths tolerantly and invalidate stale outputs *before*
    # strict parsing, so even an invalid argument fails closed (no consumable
    # out-of-date report survives the run).
    path_args, _ = _build_path_parser().parse_known_args()

    input_paths = {path_args.dataset.resolve(), path_args.corpus.resolve()}
    output_paths = {path_args.report.resolve(), path_args.review.resolve()}
    all_paths = (path_args.dataset, path_args.corpus, path_args.report, path_args.review)
    existing_alias = any(
        left.exists() and right.exists() and left.samefile(right)
        for index, left in enumerate(all_paths)
        for right in all_paths[index + 1:]
    )
    if len(output_paths) != 2 or output_paths & input_paths or existing_alias:
        print("VIOLATION: output paths must be distinct from inputs and each other",
              file=sys.stderr)
        return 1
    try:
        _invalidate_outputs((path_args.report, path_args.review))
    except OSError:
        print("VIOLATION: unable to invalidate previous campaign artifacts",
              file=sys.stderr)
        return 1

    # Strict parse now; an invalid argument exits with code 2 *after* the stale
    # artifacts have already been removed above.
    args = _build_parser().parse_args()

    cases = load_cases(args.dataset)
    documents = load_documents(args.corpus)

    if any(is_quality_eligible(c) for c in cases):
        print("VIOLATION: a quality-eligible case is present in the synthetic track",
              file=sys.stderr)
        return 1

    service = build_public_service(documents, minimum_score=args.minimum_score, top_k=1)
    context = AuthorizationContext(
        tenant_id="public", user_id="evaluator", groups=(), clearance=0
    )

    def rag_answer(question: str) -> str:
        trace = service.answer_with_trace(question, context=context)
        return RAG_ABSTENTION if trace.response.abstained else trace.response.answer

    # Baseline side: use the real closed-book generator when RAG_BASELINE_* is
    # configured, otherwise abstain honestly (no endpoint to answer from).
    baseline = build_baseline_generator(env=os.environ)
    if baseline is not None:
        def closed_book_answer(question: str) -> str:
            return baseline(question)
    else:
        def closed_book_answer(_question: str) -> str:
            return CLOSED_BOOK_ABSTENTION

    try:
        result = compare_campaigns(
            cases,
            rag_answer,
            closed_book_answer,
            review_fraction=args.review_fraction,
            seed=args.seed,
        )
    except GenerationError:
        print("BACKEND_ERROR: generator unavailable", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"VIOLATION: {exc}", file=sys.stderr)
        return 1

    report = {
        "track": "synthetic",
        "note": (
            "OFFLINE comparison. RAG = extractive top-chunk answer; closed-book "
            "abstains (no endpoint). Abstention axis is real; answer correctness "
            "is left to the >=20% human review."
        ),
        "total": result.total,
        "review_fraction": args.review_fraction,
        "review_sample_size": len(result.review_sample),
        "rag_abstention_precision": result.rag_abstention_precision,
        "rag_abstention_recall": result.rag_abstention_recall,
        "closed_book_abstention_precision": result.closed_book_abstention_precision,
        "closed_book_abstention_recall": result.closed_book_abstention_recall,
    }

    report_content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"

    # Human-review file: one pair per line, with empty verdict fields to fill.
    review_lines = []
    for pair in result.review_sample:
        record = asdict(pair)
        record["human_verdict"] = {
            "rag_correct": None,
            "closed_book_correct": None,
            "notes": "",
        }
        review_lines.append(json.dumps(record, ensure_ascii=False))
    review_content = "\n".join(review_lines) + "\n"

    try:
        _publish_artifacts(args.report, report_content, args.review, review_content)
    except OSError:
        print("VIOLATION: unable to publish campaign artifacts", file=sys.stderr)
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nreview sample -> {args.review} ({len(result.review_sample)} pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
