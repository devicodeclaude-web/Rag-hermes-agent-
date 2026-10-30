#!/usr/bin/env python3
from __future__ import annotations

import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import statistics
import time
from dataclasses import asdict

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer
from FlagEmbedding import BGEM3FlagModel, FlagReranker

from rag_hermes.abstention_calibration import (
    calibrate_threshold,
    deterministic_group_split,
    gpu_execution_metadata,
    gpu_report_limitations,
    human_cases_to_questions,
    human_evidence_counts,
    invalidate_gpu_output,
    publish_gpu_report_atomic,
    read_clean_repository_revision,
    read_model_lock_snapshots,
    read_repository_json_snapshot,
    read_repository_snapshot,
    require_clean_code_revision,
    reranker_truncation_evidence,
    score_human_retrieval,
    score_threshold,
    validate_campaign_shape,
    validate_gpu_hardware,
)
from rag_hermes.acl import AuthorizationContext, filter_authorized
from rag_hermes.acl_authority import AclPolicy, CanonicalAclAuthority
from rag_hermes.benchmark import BenchmarkQuestion
from rag_hermes.dataset import load_documents_payload
from rag_hermes.eval_corpus import (
    corpus_manifest_payload,
    load_documents_payload as load_evaluation_documents_payload,
)
from rag_hermes.evaluation import EvaluationCase, evaluate
from rag_hermes.ingestion import chunk_document_tokens
from rag_hermes.retrieval import hybrid_rrf_indices, postfilter_candidates, score_authorized_pairs

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(os.environ.get(
    "RAG_GPU_MANIFEST", ROOT / "manifests/gpu/bge-m3-smoke-rtx4090.json"
))
OUTPUT = Path(os.environ.get(
    "RAG_GPU_OUTPUT", ROOT / "data/results/bge_m3_gpu_smoke_report.json"
))
MODEL_ROOT = Path(os.environ.get("RAG_MODEL_ROOT", Path.home() / "models"))
CALIBRATION_SALT = "bge-m3-abstention-v1"
RANDOM_SEED = 1542026


def configure_determinism() -> dict[str, object]:
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    torch.manual_seed(RANDOM_SEED)
    torch.cuda.manual_seed_all(RANDOM_SEED)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    return {
        "python_random_seed": RANDOM_SEED,
        "numpy_random_seed": RANDOM_SEED,
        "torch_random_seed": RANDOM_SEED,
        "torch_cuda_random_seed": RANDOM_SEED,
        "torch_deterministic_algorithms": True,
        "cudnn_deterministic": True,
        "cudnn_benchmark": False,
        "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
        "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
        "known_limitations": [
            "PYTHONHASHSEED is effective only when supplied before interpreter startup.",
            "Bitwise identity is not promised across GPU models, CUDA/PyTorch versions, "
            "or third-party FlagEmbedding implementations.",
        ],
    }


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_locked_files(directory: Path, lock: dict) -> list[dict]:
    verified = []
    for item in lock["files"]:
        path = directory / item["path"]
        if not path.is_file():
            raise RuntimeError(f"locked artifact missing: {path}")
        actual_size = path.stat().st_size
        if actual_size != int(item["size"]):
            raise RuntimeError(f"size mismatch: {path}: {actual_size} != {item['size']}")
        actual_sha = sha256(path) if item.get("sha256") else None
        if item.get("sha256") and actual_sha != item["sha256"]:
            raise RuntimeError(f"sha256 mismatch: {path}")
        verified.append({"path": item["path"], "size": actual_size, "sha256": actual_sha})
    return verified


def sparse_dot(a: dict, b: dict) -> float:
    if len(a) > len(b):
        a, b = b, a
    return float(sum(float(value) * float(b.get(key, 0.0)) for key, value in a.items()))


def ranks_desc(scores: list[float]) -> list[int]:
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    ranks = [0] * len(scores)
    for rank, index in enumerate(order, 1):
        ranks[index] = rank
    return ranks


def main() -> None:
    invalidate_gpu_output(
        OUTPUT,
        ROOT / "data/results",
        protected_paths=[MANIFEST],
    )
    expected_manifest_sha = os.environ.get("RAG_GPU_MANIFEST_SHA256")
    manifest, manifest_attestation = read_repository_json_snapshot(
        ROOT, MANIFEST, expected_manifest_sha
    )
    manifest_path = os.environ.get("RAG_GPU_MANIFEST_PATH", manifest_attestation["path"])
    is_human_manifest = manifest["corpus"].get("question_format") == "evaluation_v2"
    if is_human_manifest:
        if not expected_manifest_sha:
            raise ValueError("human GPU evaluation requires an attested manifest SHA-256")
        expected_manifest_path = (ROOT / manifest_path).resolve()
        if expected_manifest_path != MANIFEST.resolve():
            raise ValueError("attested manifest path does not match RAG_GPU_MANIFEST")
        code_revision = require_clean_code_revision(
            os.environ.get("RAG_CODE_REVISION"),
            read_clean_repository_revision(ROOT),
            "",
        )
    else:
        code_revision = os.environ.get("RAG_CODE_REVISION")
    determinism = configure_determinism()
    protocol_payload, protocol_attestation = read_repository_snapshot(
        ROOT, ROOT / "docs/ablation-protocol.md"
    )
    props = torch.cuda.get_device_properties(0)
    validated_hardware = validate_gpu_hardware(
        torch.cuda.get_device_name(0), props.total_memory, manifest
    )
    model_locks = read_model_lock_snapshots(ROOT, manifest)
    emb_lock = model_locks["embedding"]["data"]
    rerank_lock = model_locks["reranker"]["data"]
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)

    corpus_items = manifest["corpus"]["documents"]
    if not corpus_items:
        raise ValueError("GPU manifest must name at least one corpus file")
    corpus_payload, corpus_attestation = read_repository_snapshot(
        ROOT, ROOT / corpus_items[0]
    )
    corpus_snapshots = [(corpus_payload, corpus_attestation)] + [
        read_repository_snapshot(ROOT, ROOT / item) for item in corpus_items[1:]
    ]
    documents = load_documents_payload(corpus_payload)
    for payload, _attestation in corpus_snapshots[1:]:
        documents.extend(load_documents_payload(payload))
    human_cases = None
    campaign_counts = None
    evaluation_documents = None
    evaluation_manifest = None
    split_assignments: dict[str, str] = {}
    dataset_path = ROOT / manifest["corpus"]["questions"]
    dataset_payload, dataset_attestation = read_repository_snapshot(ROOT, dataset_path)
    dataset_rows = [
        json.loads(line)
        for line in dataset_payload.decode("utf-8").splitlines()
        if line.strip()
    ]
    if is_human_manifest:
        raw_cases = dataset_rows
        evaluation_documents = load_evaluation_documents_payload(corpus_payload)
        evaluation_manifest = corpus_manifest_payload(corpus_payload)
        human_cases, questions = human_cases_to_questions(
            raw_cases, evaluation_documents, evaluation_manifest
        )
        split_assignments = deterministic_group_split(
            human_cases, salt=CALIBRATION_SALT
        )
        campaign_counts = validate_campaign_shape(
            human_cases, split_assignments, manifest["campaign"]
        )
    else:
        questions = [
            BenchmarkQuestion(
                case_id=row["case_id"],
                question=row["question"],
                context=AuthorizationContext(
                    tenant_id=row["tenant_id"],
                    user_id=row["user_id"],
                    groups=tuple(row["groups"]),
                    clearance=int(row["clearance"]),
                ),
                relevant_document_ids=tuple(row["relevant_document_ids"]),
                should_abstain=bool(row["should_abstain"]),
            )
            for row in dataset_rows
        ]
    execution_receipt = os.environ.get("RAG_EXECUTION_RECEIPT")
    execution_metadata = gpu_execution_metadata(
        is_human=human_cases is not None,
        receipt_path=execution_receipt,
    )
    if execution_receipt is not None:
        execution_metadata["artifact_source_of_truth"] = "execution_receipt.report"
        execution_metadata["staging_report_consumable"] = False
    else:
        execution_metadata["artifact_source_of_truth"] = "standalone_gpu_report"
        execution_metadata["staging_report_consumable"] = True

    download_started = time.perf_counter()
    emb_dir = Path(snapshot_download(
        repo_id=emb_lock["repo_id"], revision=emb_lock["revision"],
        local_dir=MODEL_ROOT / "bge-m3", local_dir_use_symlinks=False,
    ))
    rerank_dir = Path(snapshot_download(
        repo_id=rerank_lock["repo_id"], revision=rerank_lock["revision"],
        local_dir=MODEL_ROOT / "bge-reranker-v2-m3", local_dir_use_symlinks=False,
    ))
    verified_embedding = verify_locked_files(emb_dir, emb_lock)
    verified_reranker = verify_locked_files(rerank_dir, rerank_lock)
    download_seconds = time.perf_counter() - download_started

    chunking = manifest["chunking"]
    tokenizer = AutoTokenizer.from_pretrained(str(rerank_dir), local_files_only=True)
    question_token_counts = [
        len(tokenizer(question.question, add_special_tokens=False, truncation=False)["input_ids"])
        for question in questions
    ]
    if any(count > int(chunking["question_max_tokens"]) for count in question_token_counts):
        raise RuntimeError(
            f"question token budget exceeded: {question_token_counts}; "
            f"limit={chunking['question_max_tokens']}"
        )
    chunks = [
        chunk
        for document in documents
        for chunk in chunk_document_tokens(
            document,
            tokenizer,
            max_passage_tokens=int(chunking["passage_max_tokens"]),
            overlap_tokens=int(chunking["overlap_tokens"]),
            tokenizer_name=chunking["tokenizer"],
            tokenizer_revision=chunking["tokenizer_revision"],
        )
    ]
    authority = CanonicalAclAuthority({
        document.document_id: AclPolicy(
            document.tenant_id, document.visibility, document.owner_id,
            document.allowed_groups, document.allowed_users,
            document.classification, document.acl_version,
        )
        for document in documents
    })
    texts = [chunk.text for chunk in chunks]

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    embedder = BGEM3FlagModel(str(emb_dir), use_fp16=True, device="cuda")
    embed_started = time.perf_counter()
    corpus_output = embedder.encode(
        texts,
        batch_size=int(manifest["embedding"]["batch_size"]),
        max_length=int(manifest["embedding"]["max_length"]),
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    query_output = embedder.encode(
        [question.question for question in questions],
        batch_size=int(manifest["embedding"]["batch_size"]),
        max_length=int(manifest["embedding"]["max_length"]),
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    torch.cuda.synchronize()
    embedding_seconds = time.perf_counter() - embed_started
    embedding_peak_gib = torch.cuda.max_memory_allocated() / (1024 ** 3)

    corpus_dense = np.asarray(corpus_output["dense_vecs"], dtype=np.float32)
    query_dense = np.asarray(query_output["dense_vecs"], dtype=np.float32)
    corpus_sparse = corpus_output["lexical_weights"]
    query_sparse = query_output["lexical_weights"]
    if corpus_dense.shape != (len(chunks), int(manifest["embedding"]["dense_dimension"])):
        raise RuntimeError(f"unexpected dense shape: {corpus_dense.shape}")

    hybrid_candidates: list[list[int]] = []
    pre_cases: list[EvaluationCase] = []
    pre_case_details = []
    for q_index, question in enumerate(questions):
        authorized_chunks = filter_authorized(chunks, question.context)
        authorized_ids = {chunk.chunk_id for chunk in authorized_chunks}
        indices = [i for i, chunk in enumerate(chunks) if chunk.chunk_id in authorized_ids]
        dense_scores = [float(np.dot(query_dense[q_index], corpus_dense[i])) for i in indices]
        sparse_scores = [sparse_dot(query_sparse[q_index], corpus_sparse[i]) for i in indices]
        hybrid = manifest["hybrid"]
        top = hybrid_rrf_indices(
            candidate_indices=indices, dense_scores=dense_scores,
            sparse_scores=sparse_scores,
            dense_limit=int(hybrid["dense_candidates"]),
            sparse_limit=int(hybrid["sparse_candidates"]),
            output_limit=int(hybrid["reranker_candidates"]),
            fusion_k=int(hybrid["fusion_k"]),
            dense_weight=float(hybrid["dense_weight"]),
            sparse_weight=float(hybrid["sparse_weight"]),
        )
        hybrid_candidates.append(top)
        retrieved_docs = tuple(dict.fromkeys(chunks[i].document_id for i in top[:10]))
        pre_cases.append(EvaluationCase(
            case_id=question.case_id,
            relevant_chunk_ids=question.relevant_document_ids,
            retrieved_chunk_ids=retrieved_docs,
            cited_chunk_ids=(), should_abstain=question.should_abstain,
            did_abstain=False,
            leaked_chunk_ids=tuple(doc for doc in retrieved_docs if chunks[next(i for i in top if chunks[i].document_id == doc)].tenant_id not in {question.context.tenant_id, "public"}),
        ))
        relevant = set(question.relevant_document_ids)
        first_relevant_rank = next(
            (rank for rank, document_id in enumerate(retrieved_docs, 1) if document_id in relevant),
            None,
        )
        pre_case_details.append({
            "retrieved_document_ids": list(retrieved_docs),
            "first_relevant_rank": first_relevant_rank,
            "hit": first_relevant_rank is not None,
        })

    del embedder, corpus_output, query_output
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()

    reranker = FlagReranker(str(rerank_dir), use_fp16=True, device="cuda")
    rerank_started = time.perf_counter()
    post_cases: list[EvaluationCase] = []
    case_details = []
    ranked_by_case: dict[str, dict[str, object]] = {}
    rejected_pairs = 0
    acl_barrier_totals = {"examined": 0, "accepted": 0, "stale_acl_version": 0, "denied_by_authority": 0}
    observed_lengths = []
    for question, candidate_indices, pre_detail in zip(
        questions, hybrid_candidates, pre_case_details
    ):
        candidates = [{"payload": {
            "document_id": chunks[index].document_id,
            "acl_version": chunks[index].acl_version,
            "text": chunks[index].text,
            "chunk_index": index,
        }} for index in candidate_indices]
        authorized, acl_counters = postfilter_candidates(candidates, question.context, authority)
        for key in acl_barrier_totals:
            acl_barrier_totals[key] += getattr(acl_counters, key)
        if authorized:
            scores, budget_counters = score_authorized_pairs(
                reranker, tokenizer, question.question, authorized,
                batch_size=int(manifest["reranker"]["batch_size"]),
                max_length=int(manifest["reranker"]["max_length"]),
            )
            rejected_pairs += budget_counters.rejected_pairs
            observed_lengths.append(budget_counters.maximum_pair_tokens)
            accepted_indices = [int(item["payload"]["chunk_index"]) for item in authorized]
            ordered = sorted(zip(accepted_indices, scores), key=lambda item: item[1], reverse=True)
        else:
            ordered = []
        top = ordered[:10]
        retrieved_docs = tuple(dict.fromkeys(chunks[i].document_id for i, _ in top))
        best_score = top[0][1] if top else None
        ranked_by_case[question.case_id] = {
            "chunks": [chunks[i] for i, _score in top],
            "best_score": best_score,
        }
        did_abstain = best_score is None or best_score < 0.5
        leaked_docs = tuple(doc for doc in retrieved_docs if chunks[next(i for i, _ in top if chunks[i].document_id == doc)].tenant_id not in {question.context.tenant_id, "public"})
        post_cases.append(EvaluationCase(
            case_id=question.case_id,
            relevant_chunk_ids=question.relevant_document_ids,
            retrieved_chunk_ids=retrieved_docs,
            cited_chunk_ids=(), should_abstain=question.should_abstain,
            did_abstain=did_abstain, leaked_chunk_ids=leaked_docs,
        ))
        relevant = set(question.relevant_document_ids)
        first_relevant_rank = next(
            (rank for rank, document_id in enumerate(retrieved_docs, 1) if document_id in relevant),
            None,
        )
        case_details.append({
            "case_id": question.case_id,
            "track": (
                human_cases[len(case_details)]["track"] if human_cases is not None else None
            ),
            "calibration_partition": split_assignments.get(question.case_id),
            "should_abstain": question.should_abstain,
            "relevant_document_ids": list(question.relevant_document_ids),
            "question_token_count": question_token_counts[len(case_details)],
            "pre_rerank": pre_detail,
            "best_score": best_score,
            "did_abstain": did_abstain,
            "post_rerank": {
                "retrieved_document_ids": list(retrieved_docs),
                "first_relevant_rank": first_relevant_rank,
                "hit": first_relevant_rank is not None,
            },
        })

    torch.cuda.synchronize()
    reranker_seconds = time.perf_counter() - rerank_started
    reranker_peak_gib = torch.cuda.max_memory_allocated() / (1024 ** 3)
    pre_report = asdict(evaluate(pre_cases, k=10))
    post_report = asdict(evaluate(post_cases, k=10))
    abstention_calibration = None
    if human_cases is not None:
        if evaluation_documents is None or evaluation_manifest is None:
            raise RuntimeError("human evaluation corpus metadata was not initialized")
        calibration_rows = [
            row for row in case_details
            if row["calibration_partition"] == "calibration"
        ]
        holdout_rows = [
            row for row in case_details
            if row["calibration_partition"] == "holdout"
        ]
        fitted = calibrate_threshold(calibration_rows)
        threshold = fitted["threshold"]
        abstention_calibration = {
            "salt": CALIBRATION_SALT,
            "grouping_key": "pair_id_fallback_case_id",
            "selection_data": "calibration_partition_only",
            "objective": fitted["objective"],
            "tie_break": fitted["tie_break"],
            "threshold": threshold,
            "calibration": fitted["metrics"],
            "holdout": score_threshold(holdout_rows, threshold=threshold),
            "holdout_passage_metrics": score_human_retrieval(
                [
                    case for case in human_cases
                    if split_assignments[str(case["case_id"])] == "holdout"
                ],
                evaluation_documents,
                evaluation_manifest,
                ranked_by_case,
                threshold=threshold,
                k=10,
            ),
            "holdout_by_track": {
                track: score_threshold(
                    [row for row in holdout_rows if row["track"] == track],
                    threshold=threshold,
                )
                for track in sorted({row["track"] for row in holdout_rows})
            },
        }

    evidence_counts = (
        human_evidence_counts(human_cases)
        if human_cases is not None
        else {"questions_total": len(questions), "independent_manual_questions": 0}
    )
    report = {
        "job_id": manifest["job_id"],
        "code_revision": code_revision,
        "audited_commit": code_revision,
        "execution": execution_metadata,
        "status": (
            "intermediate_human_component_evaluation"
            if human_cases is not None
            else "infrastructure_smoke_only"
        ),
        "result_classification": (
            "human_component_evaluation_with_calibration_holdout_not_production"
            if human_cases is not None
            else "not_a_quality_benchmark"
        ),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reproducibility": determinism,
        "hardware": {
            **validated_hardware,
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "python": platform.python_version(),
        },
        "artifacts": {
            "embedding_repo": emb_lock["repo_id"], "embedding_revision": emb_lock["revision"],
            "reranker_repo": rerank_lock["repo_id"], "reranker_revision": rerank_lock["revision"],
            "embedding_lock": model_locks["embedding"]["attestation"],
            "reranker_lock": model_locks["reranker"]["attestation"],
            "verified_embedding_files": verified_embedding,
            "verified_reranker_files": verified_reranker,
            "download_seconds": download_seconds,
        },
        "corpus": {
            "documents": len(documents), "chunks": len(chunks), "questions": len(questions),
            "independent_manual_questions": evidence_counts["independent_manual_questions"],
            "campaign_counts": campaign_counts,
            "corpus_path": corpus_attestation["path"],
            "corpus_sha256": corpus_attestation["sha256"],
            "sources": [attestation for _payload, attestation in corpus_snapshots],
        },
        "protocol": {
            "manifest_path": manifest_path,
            "manifest_sha256": manifest_attestation["sha256"],
            "path": protocol_attestation["path"],
            "sha256": protocol_attestation["sha256"],
            "dataset_path": dataset_attestation["path"],
            "dataset_sha256": dataset_attestation["sha256"],
        },
        "hybrid": manifest["hybrid"],
        "chunking": {
            **chunking,
            "maximum_observed_chunk_tokens": max(chunk.token_count for chunk in chunks),
        },
        "embedding": {
            "dense_dimension": int(corpus_dense.shape[1]),
            "seconds": embedding_seconds,
            "chunks_per_second": len(chunks) / embedding_seconds,
            "peak_allocated_vram_gib": embedding_peak_gib,
            "sparse_nonzero_mean": statistics.fmean(len(x) for x in corpus_sparse),
        },
        "reranker": {
            "seconds": reranker_seconds,
            "peak_allocated_vram_gib": reranker_peak_gib,
            "max_length": int(manifest["reranker"]["max_length"]),
            "truncation_policy": "reject",
            **reranker_truncation_evidence(
                rejected_pairs=rejected_pairs,
                maximum_observed_pair_tokens=max(observed_lengths, default=0),
            ),
        },
        "metrics_hybrid_pre_rerank": pre_report,
        "metrics_after_rerank": post_report,
        "abstention_calibration": abstention_calibration,
        "acl_evidence": {
            "scope": "python_prefilter_plus_canonical_authority_postfilter_before_reranking",
            "qdrant_exercised": False,
            "security_claim": "none_for_qdrant_or_complete_multitenant_system",
            "postfilter_counters": acl_barrier_totals,
        },
        "quality_gate_passed": False,
        "cases": case_details,
        "limitations": gpu_report_limitations(is_human=human_cases is not None),
    }
    publish_gpu_report_atomic(OUTPUT, ROOT / "data/results", report)
    print(json.dumps({
        "staging_output": str(OUTPUT), "documents": len(documents), "chunks": len(chunks),
        "questions": len(questions), "embedding_seconds": embedding_seconds,
        "reranker_seconds": reranker_seconds, "embedding_peak_gib": embedding_peak_gib,
        "reranker_peak_gib": reranker_peak_gib, "post_metrics": post_report,
    }, indent=2))


if __name__ == "__main__":
    main()
