#!/usr/bin/env python3
"""Run Step 1 retrieval ablations with explicit deterministic fake models.

The built-in fakes exercise retrieval, fusion, reranking, token-budget and
passage-span evaluation mechanics only.  They are deliberately not model-quality
evidence and never download weights.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_hermes.acl import Chunk
from rag_hermes.evaluation_runner import RetrievedChunk, run_evaluation
from rag_hermes.eval_corpus import corpus_manifest, load_documents, sha256_of_file
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.quality_track import FROZEN_HUMAN_CORPUS, FROZEN_HUMAN_DATASET
from rag_hermes.reranker_budget import count_pair_tokens
from rag_hermes.retrieval import hybrid_rrf_indices

RESULTS = ROOT / "data/results/step1-retrieval-ablation-fake.json"
MODES = (
    "bm25",
    "dense",
    "sparse",
    "hybrid_dense_sparse",
    "hybrid_bm25_dense_sparse",
    "hybrid_bm25_dense_sparse_reranked",
)
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_EXPECTED_DATASET_SHA256 = "4613e8b3b84fb7b24ad66cf01329f40d95934bec189fe7f6cddf1eb751c767d4"
_EXPECTED_CORPUS_SHA256 = "af0631abbffaab14b180abc4531497665a6104d6685328d6abbe53a565c53866"
_EXPECTED_SOURCE_REVISION = "b682a98ab8cb30c4f0561021e0ff9f41e5156526"


@lru_cache(maxsize=None)
def _cached_tokens(text: str) -> Counter[str]:
    return Counter(token.casefold() for token in _TOKEN_RE.findall(text))


class _CachedBm25:
    """Same BM25 formula as LexicalRetriever, with corpus terms cached once."""

    def __init__(self, chunks: Sequence[Chunk]):
        self._terms = [_cached_tokens(chunk.text) for chunk in chunks]
        self._document_count = len(self._terms)
        self._average_length = sum(sum(terms.values()) for terms in self._terms) / self._document_count
        self._document_frequency: Counter[str] = Counter()
        for terms in self._terms:
            self._document_frequency.update(terms.keys())

    def scores(self, query: str) -> list[float]:
        query_terms = _cached_tokens(query)
        scores = []
        for terms in self._terms:
            document_length = sum(terms.values())
            raw_score = 0.0
            for term, query_count in query_terms.items():
                term_frequency = terms.get(term, 0)
                if not term_frequency:
                    continue
                inverse_document_frequency = math.log(
                    1.0
                    + (self._document_count - self._document_frequency[term] + 0.5)
                    / (self._document_frequency[term] + 0.5)
                )
                saturation = term_frequency * 2.2 / (
                    term_frequency
                    + 1.2 * (1.0 - 0.75 + 0.75 * document_length / self._average_length)
                )
                raw_score += inverse_document_frequency * saturation * query_count
            scores.append(raw_score / (raw_score + 1.0) if raw_score else 0.0)
        return scores


def attest_frozen_inputs(dataset: Path, corpus: Path) -> dict[str, Any]:
    """Fail closed unless paths and bytes are the reviewed 154/461 snapshots."""
    if dataset.resolve() != FROZEN_HUMAN_DATASET.resolve() or corpus.resolve() != FROZEN_HUMAN_CORPUS.resolve():
        raise ValueError("inputs must use the canonical frozen snapshot path")
    dataset_sha = sha256_of_file(dataset)
    corpus_sha = sha256_of_file(corpus)
    if dataset_sha != _EXPECTED_DATASET_SHA256 or corpus_sha != _EXPECTED_CORPUS_SHA256:
        raise ValueError("frozen snapshot hash mismatch")
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    documents = load_documents(corpus)
    manifest = corpus_manifest(corpus)
    if len(cases) != 154 or len(documents) != 461:
        raise ValueError("frozen snapshots must contain exactly 154 cases and 461 documents")
    if manifest["source_revision"] != _EXPECTED_SOURCE_REVISION or manifest["corpus_manifest_sha"] != _EXPECTED_CORPUS_SHA256:
        raise ValueError("frozen corpus manifest mismatch")
    return {
        "dataset_path": str(dataset.resolve()),
        "corpus_path": str(corpus.resolve()),
        "dataset_sha256": dataset_sha,
        "corpus_sha256": corpus_sha,
        "source_revision": manifest["source_revision"],
        "corpus_manifest_sha": manifest["corpus_manifest_sha"],
        "cases": len(cases),
        "corpus_documents": len(documents),
    }


class FakeTokenizer:
    """Dependency-free tokenizer with the tiny HF surface used by this runner."""

    name = "fake_regex_tokenizer"
    revision = "mechanism-only-v1"

    def __call__(
        self,
        text: str,
        text_pair: str | None = None,
        *,
        add_special_tokens: bool,
        truncation: bool,
        return_offsets_mapping: bool = False,
    ) -> dict[str, Any]:
        if truncation:
            raise ValueError("fake tokenizer refuses truncation")
        matches = list(_TOKEN_RE.finditer(text))
        ids = [self._token_id(match.group()) for match in matches]
        if text_pair is not None:
            pair_matches = list(_TOKEN_RE.finditer(text_pair))
            pair_ids = [self._token_id(match.group()) for match in pair_matches]
            ids = ([1] if add_special_tokens else []) + ids + ([2] if add_special_tokens else []) + pair_ids + ([3] if add_special_tokens else [])
        elif add_special_tokens:
            ids = [1, *ids, 2]
        result: dict[str, Any] = {"input_ids": ids}
        if return_offsets_mapping:
            if text_pair is not None or add_special_tokens:
                raise ValueError("offset mappings are only supported for plain text")
            result["offset_mapping"] = [(match.start(), match.end()) for match in matches]
        return result

    @staticmethod
    def _token_id(token: str) -> int:
        return int(hashlib.sha256(token.casefold().encode()).hexdigest()[:8], 16)


class FakeEmbedder:
    """Deterministic lexical signals exposed as fake dense/sparse model scores."""

    name = "fake_deterministic_embedder"
    revision = "mechanism-only-v1"

    @staticmethod
    def _tokens(text: str) -> Counter[str]:
        return _cached_tokens(text)

    def dense_score(self, query: str, passage: str) -> float:
        left, right = set(self._tokens(query)), set(self._tokens(passage))
        overlap = len(left.intersection(right)) / max(1, len(left.union(right)))
        epsilon = int(hashlib.sha256((query + "\0" + passage).encode()).hexdigest()[:6], 16) / 0xFFFFFF
        return overlap + epsilon * 1e-6

    def sparse_score(self, query: str, passage: str) -> float:
        query_terms, passage_terms = self._tokens(query), self._tokens(passage)
        return float(sum(min(count, passage_terms.get(term, 0)) for term, count in query_terms.items()))


class FakeReranker:
    """Deterministic overlap scorer implementing FlagEmbedding's method shape."""

    name = "fake_deterministic_reranker"
    revision = "mechanism-only-v1"

    def compute_score(self, pairs, *, batch_size: int, max_length: int, normalize: bool):
        del batch_size, max_length
        scores = []
        for query, passage in pairs:
            query_terms = set(token.casefold() for token in _TOKEN_RE.findall(query))
            passage_terms = set(token.casefold() for token in _TOKEN_RE.findall(passage))
            score = len(query_terms.intersection(passage_terms)) / max(1, len(query_terms))
            scores.append(score if normalize else score * 2.0 - 1.0)
        return scores


def _three_way_rrf_indices(
    candidate_indices: Sequence[int],
    bm25_scores: Sequence[float],
    dense_scores: Sequence[float],
    sparse_scores: Sequence[float],
    *,
    limit: int,
    fusion_k: int = 60,
) -> list[int]:
    """Fuse three rankings by summing each independent RRF contribution."""
    if not (len(candidate_indices) == len(bm25_scores) == len(dense_scores) == len(sparse_scores)):
        raise ValueError("candidate and score lengths differ")
    if limit < 1 or fusion_k < 1:
        raise ValueError("RRF limit and fusion_k must be positive")
    fused: dict[int, float] = {}
    for score_index, scores in enumerate((bm25_scores, dense_scores, sparse_scores)):
        positions = range(len(candidate_indices))
        if score_index == 0:
            positions = (position for position in positions if scores[position] > 0.0)
        order = sorted(
            positions,
            key=lambda position: (-scores[position], candidate_indices[position]),
        )[:limit]
        for rank, position in enumerate(order, 1):
            index = candidate_indices[position]
            fused[index] = fused.get(index, 0.0) + 1.0 / (fusion_k + rank)
    return [
        index
        for index, _score in sorted(fused.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _git_state() -> dict[str, Any]:
    """Read repository identity without honoring caller-supplied Git routing."""
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        return completed.stdout

    audited_commit = git("rev-parse", "--verify", "HEAD").strip()
    if re.fullmatch(r"[0-9a-f]{40}", audited_commit) is None:
        raise ValueError("Git HEAD must resolve to a lowercase SHA-40")
    return {
        "audited_commit": audited_commit,
        "working_tree_dirty": bool(git("status", "--porcelain=v1").strip()),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--dataset", type=Path, default=FROZEN_HUMAN_DATASET)
    parser.add_argument("--corpus", type=Path, default=FROZEN_HUMAN_CORPUS)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--fake-models", action="store_true", required=True)
    return parser


def _document(document_id: str, raw: Mapping[str, Any]) -> Document:
    return Document(
        document_id=document_id,
        content=str(raw["content"]),
        tenant_id=str(raw.get("tenant_id", "public")),
        visibility=str(raw.get("visibility", "public")),
        owner_id=str(raw.get("owner_id", "evaluator")),
        allowed_groups=tuple(raw.get("allowed_groups", ())),
        allowed_users=tuple(raw.get("allowed_users", ())),
        classification=int(raw.get("classification", 0)),
        doc_version=int(raw.get("doc_version", 1)),
        source_uri=str(raw.get("source_uri", f"evaluation://{document_id}")),
        acl_version=int(raw.get("acl_version", 1)),
    )


def _score_subset(cases, documents, manifest, records, *, k: int, threshold: float | None = None):
    def answer_fn(_question, case):
        record = records[str(case["case_id"])]
        retrieved = tuple(RetrievedChunk(chunk) for chunk in record["chunks"])
        if threshold is None:
            cited = retrieved
        else:
            cited = tuple(
                RetrievedChunk(chunk)
                for chunk, score in zip(record["chunks"], record["scores"])
                if score >= threshold
            )
        return retrieved, cited, not cited

    report = run_evaluation(cases, documents, manifest, answer_fn, k=k)
    return {
        "cases_total": len(cases),
        "cases_answerable": sum(not bool(case["should_abstain"]) for case in cases),
        "cases_abstention": sum(bool(case["should_abstain"]) for case in cases),
        "metrics": asdict(report),
    }


def _evaluate_records(cases, documents, manifest, records, *, k: int, threshold: float | None = None):
    overall = _score_subset(cases, documents, manifest, records, k=k, threshold=threshold)
    by_track = {}
    for track in sorted({str(case["track"]) for case in cases}):
        subset = [case for case in cases if case["track"] == track]
        by_track[track] = _score_subset(subset, documents, manifest, records, k=k, threshold=threshold)
    return {"overall": overall, "by_track": by_track}


def run_ablation(
    cases: Sequence[Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
    *,
    embedder: Any,
    reranker: Any,
    tokenizer: Any,
    k: int = 5,
    max_pair_tokens: int = 512,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Exercise all six retrieval paths and score them through run_evaluation."""
    if k != 5:
        raise ValueError("Step 1 requires exactly k=5")
    if not cases:
        raise ValueError("at least one case is required")

    chunks: list[Chunk] = []
    for document_id, raw in documents.items():
        if raw.get("visibility") == "public":
            chunks.extend(chunk_document(_document(document_id, raw), max_tokens=300, overlap_tokens=40))
    if not chunks:
        raise ValueError("public corpus produced no chunks")

    lexical = _CachedBm25(chunks)
    records_by_mode: dict[str, dict[str, dict[str, Any]]] = {mode: {} for mode in MODES}
    contexts = []
    checked_pairs = rejected_pairs = maximum_pair_tokens = 0

    for case in cases:
        case_id, query = str(case["case_id"]), str(case["question"])
        bm25_scores = lexical.scores(query)
        dense_scores = [float(embedder.dense_score(query, chunk.text)) for chunk in chunks]
        sparse_scores = [float(embedder.sparse_score(query, chunk.text)) for chunk in chunks]
        indices = list(range(len(chunks)))
        candidate_limit = min(len(chunks), max(k, 20))

        bm25_order = sorted(
            (index for index in indices if bm25_scores[index] > 0.0),
            key=lambda i: (-bm25_scores[i], i),
        )[:k]
        dense_order = sorted(indices, key=lambda i: (-dense_scores[i], i))[:k]
        sparse_order = sorted(indices, key=lambda i: (-sparse_scores[i], i))[:k]
        dense_sparse = hybrid_rrf_indices(
            candidate_indices=indices,
            dense_scores=dense_scores,
            sparse_scores=sparse_scores,
            dense_limit=candidate_limit,
            sparse_limit=candidate_limit,
            output_limit=candidate_limit,
        )
        triple = _three_way_rrf_indices(
            indices,
            bm25_scores,
            dense_scores,
            sparse_scores,
            limit=candidate_limit,
        )
        plain_orders = {
            "bm25": bm25_order,
            "dense": dense_order,
            "sparse": sparse_order,
            "hybrid_dense_sparse": dense_sparse[:k],
            "hybrid_bm25_dense_sparse": triple[:k],
        }
        for mode, order in plain_orders.items():
            records_by_mode[mode][case_id] = {
                "chunks": [chunks[index] for index in order],
                "scores": [1.0] * len(order),
            }

        fit_pairs = []
        fit_indices = []
        for index in triple:
            pair_tokens = count_pair_tokens(tokenizer, query, chunks[index].text)
            checked_pairs += 1
            maximum_pair_tokens = max(maximum_pair_tokens, pair_tokens)
            if pair_tokens > max_pair_tokens:
                rejected_pairs += 1
                continue
            fit_pairs.append([query, chunks[index].text])
            fit_indices.append(index)
            if len(fit_pairs) == k:
                break
        if len(fit_pairs) != k:
            raise ValueError(f"case {case_id} cannot produce exactly {k} admissible contexts")
        raw_scores = reranker.compute_score(
            fit_pairs, batch_size=batch_size, max_length=max_pair_tokens, normalize=True
        )
        reranker_scores = (
            [float(raw_scores)]
            if isinstance(raw_scores, (float, int))
            else [float(score) for score in raw_scores]
        )
        if len(reranker_scores) != k or any(not math.isfinite(score) for score in reranker_scores):
            raise ValueError("reranker must return exactly five finite scores")
        ranked = sorted(zip(fit_indices, reranker_scores), key=lambda item: (-item[1], item[0]))[:k]
        records_by_mode["hybrid_bm25_dense_sparse_reranked"][case_id] = {
            "chunks": [chunks[index] for index, _score in ranked],
            "scores": [score for _index, score in ranked],
        }
        contexts.append({
            "case_id": case_id,
            "contexts": [
                {
                    "rank": rank,
                    "chunk_id": chunks[index].chunk_id,
                    "document_id": chunks[index].document_id,
                    "start_offset": chunks[index].start_offset,
                    "end_offset": chunks[index].end_offset,
                    "reranker_score": score,
                    "text": chunks[index].text,
                }
                for rank, (index, score) in enumerate(ranked, 1)
            ],
        })

    modes = {
        mode: _evaluate_records(cases, documents, manifest, records, k=k)
        for mode, records in records_by_mode.items()
    }
    reranked_records = records_by_mode["hybrid_bm25_dense_sparse_reranked"]
    sweep = []
    for threshold in (0.0, 0.25, 0.5, 0.75, 1.0):
        scored = _evaluate_records(cases, documents, manifest, reranked_records, k=k, threshold=threshold)
        sweep.append({"threshold": threshold, **scored})

    return {
        "modes": modes,
        "reranked_contexts": contexts,
        "abstention_threshold_sweep": sweep,
        "budget": {
            "max_pair_tokens": max_pair_tokens,
            "maximum_observed_pair_tokens": maximum_pair_tokens,
            "checked_pairs": checked_pairs,
            "rejected_pairs": rejected_pairs,
            "truncated_pairs": 0,
            "policy": "reject_never_truncate",
        },
    }


def _validate_payload(payload: Mapping[str, Any]) -> None:
    """Fail closed on the provenance and fixed-shape publication contract."""
    try:
        contexts = payload["results"]["reranked_contexts"]
    except (KeyError, TypeError) as exc:
        raise ValueError("results must contain reranked_contexts") from exc
    if not isinstance(contexts, list) or len(contexts) != 154:
        raise ValueError("report must contain exactly 154 case records")
    if any(
        not isinstance(record, Mapping)
        or not isinstance(record.get("contexts"), list)
        or len(record["contexts"]) != 5
        for record in contexts
    ):
        raise ValueError("every case record must contain exactly five contexts")
    case_ids = [record.get("case_id") for record in contexts]
    if any(not isinstance(case_id, str) or not case_id for case_id in case_ids):
        raise ValueError("every case record must have a non-empty case_id")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case records must have unique case_id values")

    audited_commit = payload.get("audited_commit")
    if not isinstance(audited_commit, str) or re.fullmatch(r"[0-9a-f]{40}", audited_commit) is None:
        raise ValueError("audited_commit must be a lowercase SHA-40")
    timestamp = payload.get("timestamp_utc")
    if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
        raise ValueError("timestamp_utc must be UTC")
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValueError("timestamp_utc must be ISO-8601") from exc
    if parsed_timestamp.utcoffset() != timezone.utc.utcoffset(parsed_timestamp):
        raise ValueError("timestamp_utc must be UTC")
    command = payload.get("command")
    if not isinstance(command, list) or not command or any(not isinstance(item, str) for item in command):
        raise ValueError("command must be the exact non-empty argv list")
    if type(payload.get("exit_code")) is not int or payload["exit_code"] != 0:
        raise ValueError("exit_code must be exactly zero")
    if not isinstance(payload.get("python_version"), str) or not payload["python_version"]:
        raise ValueError("python_version is required")
    if payload.get("qdrant") != "not_exercised":
        raise ValueError("Qdrant must be marked not_exercised")
    if payload.get("deterministic_seed") != 20260923:
        raise ValueError("deterministic seed mismatch")

    protocol_path = (ROOT / "docs/ablation-protocol.md").resolve()
    protocol = payload.get("protocol")
    if not isinstance(protocol, Mapping):
        raise ValueError("protocol provenance is required")
    if protocol.get("path") != str(protocol_path) or protocol.get("sha256") != sha256_of_file(protocol_path):
        raise ValueError("protocol path or SHA-256 mismatch")
    inputs = payload.get("inputs")
    if not isinstance(inputs, Mapping) or inputs.get("cases") != 154:
        raise ValueError("inputs must attest exactly 154 cases")
    dataset_sha = inputs.get("dataset_sha256")
    if not isinstance(dataset_sha, str) or re.fullmatch(r"[0-9a-f]{64}", dataset_sha) is None:
        raise ValueError("dataset SHA-256 is required")

    models = payload.get("models")
    if not isinstance(models, Mapping) or set(models) != {"embedder", "reranker", "tokenizer"}:
        raise ValueError("all fake model identities are required")
    for identity in models.values():
        if not isinstance(identity, Mapping) or set(identity) != {"name", "revision"}:
            raise ValueError("each model requires name and revision")
        if not isinstance(identity["name"], str) or not identity["name"].startswith("fake_"):
            raise ValueError("model name must identify a fake")
        if not isinstance(identity["revision"], str) or not identity["revision"]:
            raise ValueError("model revision is required")
    if type(payload.get("working_tree_dirty")) is not bool:
        raise ValueError("working_tree_dirty must be explicit")
    if payload.get("protocol_decision_eligible") is not False:
        raise ValueError("fake runner must not be protocol-decision eligible")
    expected_reasons = [
        "fake_models",
        *(["working_tree_dirty"] if payload["working_tree_dirty"] else []),
    ]
    if payload.get("protocol_decision_ineligibility_reasons") != expected_reasons:
        raise ValueError("protocol decision ineligibility reasons mismatch")
    if payload.get("fake_models_required") is not True or payload.get("quality_evidence") is not False:
        raise ValueError("fake runner evidence classification mismatch")
    if payload.get("acl") != {"scope": "public_only_mechanism_check"}:
        raise ValueError("ACL scope mismatch")

    configuration = payload.get("configuration")
    if not isinstance(configuration, Mapping) or configuration.get("k") != 5 or configuration.get("reranked_contexts_per_case") != 5:
        raise ValueError("Step 1 configuration must require exactly five contexts")
    budget = payload["results"].get("budget")
    if not isinstance(budget, Mapping) or budget.get("policy") != "reject_never_truncate" or budget.get("truncated_pairs") != 0:
        raise ValueError("budget policy mismatch")


def _fsync_directory(path: Path) -> None:
    """Persist a directory entry after atomic replacement where supported."""
    directory_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        try:
            _fsync_directory(path.parent)
        except OSError:
            # A caller that observes publication failure must not be able to
            # consume the newly renamed artifact as a successful current run.
            path.unlink(missing_ok=True)
            try:
                _fsync_directory(path.parent)
            except OSError:
                pass
            raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _validate_output_path(
    path: Path,
    dataset: Path = FROZEN_HUMAN_DATASET,
    corpus: Path = FROZEN_HUMAN_CORPUS,
) -> None:
    sources = (dataset, corpus, FROZEN_HUMAN_DATASET, FROZEN_HUMAN_CORPUS)
    for source in sources:
        if path.resolve() == source.resolve():
            raise ValueError("results path must not alias an input")
        if path.exists() and source.exists() and os.path.samefile(path, source):
            raise ValueError("results path must not hardlink an input")


def _recover_path_args(arguments: list[str]) -> argparse.Namespace:
    """Recover paths before strict parsing can exit with stale output."""
    recovered = argparse.Namespace(
        dataset=FROZEN_HUMAN_DATASET,
        corpus=FROZEN_HUMAN_CORPUS,
        results=RESULTS,
    )
    destinations = {
        "--dataset": "dataset",
        "--corpus": "corpus",
        "--results": "results",
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
    command = list(sys.argv)
    arguments = sys.argv[1:]
    if _help_requested(arguments):
        _build_parser().parse_args(arguments)

    recovered_paths = _recover_path_args(arguments)
    try:
        _validate_output_path(
            recovered_paths.results,
            recovered_paths.dataset,
            recovered_paths.corpus,
        )
        # All effective input aliases must be rejected before invalidation.
        recovered_paths.results.unlink(missing_ok=True)
    except (OSError, ValueError) as exc:
        print(f"VIOLATION: {exc}", file=sys.stderr)
        return 1

    # Strict parsing happens only after the recovered output was invalidated.
    # argparse's SystemExit intentionally preserves its normal non-zero status.
    args = _build_parser().parse_args(arguments)
    try:
        inputs = attest_frozen_inputs(args.dataset, args.corpus)
        cases = [
            json.loads(line)
            for line in args.dataset.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        documents = load_documents(args.corpus)
        manifest = corpus_manifest(args.corpus)
        results = run_ablation(
            cases,
            documents,
            manifest,
            embedder=FakeEmbedder(),
            reranker=FakeReranker(),
            tokenizer=FakeTokenizer(),
            k=5,
        )
        if any(
            mode["overall"]["metrics"]["leak_count"] != 0
            for mode in results["modes"].values()
        ):
            raise ValueError("retrieval ablation detected an authorization leak")
        protocol_path = (ROOT / "docs/ablation-protocol.md").resolve()
        git_state = _git_state()
        payload = {
            "schema_version": 1,
            "step": "step1_retrieval_ablation",
            "audited_commit": git_state["audited_commit"],
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "command": command,
            "exit_code": 0,
            "python_version": sys.version,
            "qdrant": "not_exercised",
            "deterministic_seed": 20260923,
            "protocol": {
                "path": str(protocol_path),
                "sha256": sha256_of_file(protocol_path),
            },
            "working_tree_dirty": git_state["working_tree_dirty"],
            "protocol_decision_eligible": False,
            "protocol_decision_ineligibility_reasons": [
                "fake_models",
                *(["working_tree_dirty"] if git_state["working_tree_dirty"] else []),
            ],
            "acl": {"scope": "public_only_mechanism_check"},
            "evidence_classification": "fake_models_mechanism_only_not_quality_evidence",
            "quality_evidence": False,
            "fake_models_required": True,
            "downloads_performed": False,
            "models": {
                "embedder": {
                    "name": FakeEmbedder.name,
                    "revision": FakeEmbedder.revision,
                },
                "reranker": {
                    "name": FakeReranker.name,
                    "revision": FakeReranker.revision,
                },
                "tokenizer": {
                    "name": FakeTokenizer.name,
                    "revision": FakeTokenizer.revision,
                },
            },
            "inputs": inputs,
            "configuration": {
                "k": 5,
                "modes": list(MODES),
                "reranker_max_length": 512,
                "reranker_overflow_policy": "reject_never_truncate",
                "reranked_contexts_per_case": 5,
            },
            "results": results,
            "limitations": [
                "Fake deterministic models exercise mechanisms only and cannot measure real-model retrieval quality.",
                "No torch, FlagEmbedding, GPU, cloud service, network access, or model download is used.",
                "Threshold sweep is descriptive on fake reranker scores and is not a production calibration.",
            ],
        }
        _validate_payload(payload)
        _atomic_write_json(args.results, payload)
        print(f"wrote {args.results} ({len(cases)} cases, {len(documents)} documents)")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"VIOLATION: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
