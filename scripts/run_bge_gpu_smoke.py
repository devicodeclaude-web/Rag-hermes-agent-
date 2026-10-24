#!/usr/bin/env python3
from __future__ import annotations

import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import time
from dataclasses import asdict

import numpy as np
import torch
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer
from FlagEmbedding import BGEM3FlagModel, FlagReranker

from rag_hermes.acl import filter_authorized
from rag_hermes.acl_authority import AclPolicy, CanonicalAclAuthority
from rag_hermes.dataset import load_documents, load_questions
from rag_hermes.evaluation import EvaluationCase, evaluate
from rag_hermes.ingestion import chunk_document_tokens
from rag_hermes.retrieval import hybrid_rrf_indices, postfilter_candidates, score_authorized_pairs
from rag_hermes.reranker_budget import RerankerBudgetExceeded, passage_token_budget

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests/gpu/bge-m3-smoke-rtx4090.json"
OUTPUT = ROOT / "data/results/bge_m3_gpu_smoke_report.json"
MODEL_ROOT = Path(os.environ.get("RAG_MODEL_ROOT", Path.home() / "models"))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
    manifest = load_json(MANIFEST)
    emb_lock = load_json(ROOT / manifest["models"]["embedding_lock"])
    rerank_lock = load_json(ROOT / manifest["models"]["reranker_lock"])
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)

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

    documents = []
    for item in manifest["corpus"]["documents"]:
        documents.extend(load_documents(ROOT / item))
    questions = load_questions(ROOT / manifest["corpus"]["questions"])
    chunking = manifest["chunking"]
    tokenizer = AutoTokenizer.from_pretrained(str(rerank_dir), local_files_only=True)
    # Provenance : le tokenizer declare dans le manifest doit etre celui verrouille
    # (meme objet servant au chunking ET au budget du reranker).
    if chunking["tokenizer"] != rerank_lock["repo_id"] or chunking["tokenizer_revision"] != rerank_lock["revision"]:
        raise RuntimeError(
            "chunking tokenizer/revision diverge du reranker verrouille: "
            f"{chunking['tokenizer']}@{chunking['tokenizer_revision']} != "
            f"{rerank_lock['repo_id']}@{rerank_lock['revision']}"
        )
    # Garantie structurelle : passage + marge question + reserve speciaux <= budget.
    structural_passage_budget = passage_token_budget(
        reranker_max_length=int(manifest["reranker"]["max_length"]),
        question_token_margin=int(chunking["question_max_tokens"]),
        special_token_reserve=int(chunking["special_token_reserve"]),
    )
    if int(chunking["passage_max_tokens"]) > structural_passage_budget:
        raise RuntimeError(
            f"passage_max_tokens {chunking['passage_max_tokens']} exceeds structural budget "
            f"{structural_passage_budget}"
        )
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
        token_budget_error = False
        rejected_count = 0
        if authorized:
            try:
                scores, budget_counters = score_authorized_pairs(
                    reranker, tokenizer, question.question, authorized,
                    batch_size=int(manifest["reranker"]["batch_size"]),
                    max_length=int(manifest["reranker"]["max_length"]),
                )
            except RerankerBudgetExceeded:
                # Toutes les paires hors budget -> ERROR_TOKEN_BUDGET
                # (echec, jamais une abstention, jamais retire du denominateur).
                token_budget_error = True
                rejected_count = len(authorized)
                rejected_pairs += rejected_count
                ordered = []
            else:
                observed_lengths.append(budget_counters.maximum_pair_tokens)
                rejected_count = budget_counters.rejected_pairs
                rejected_pairs += rejected_count
                accepted_indices = [int(item["payload"]["chunk_index"]) for item in budget_counters.scored]
                ordered = sorted(zip(accepted_indices, scores), key=lambda item: item[1], reverse=True)
        else:
            ordered = []
        top = ordered[:10]
        retrieved_docs = tuple(dict.fromkeys(chunks[i].document_id for i, _ in top))
        best_score = top[0][1] if top else None
        did_abstain = (not token_budget_error) and (best_score is None or best_score < 0.5)
        leaked_docs = tuple(doc for doc in retrieved_docs if chunks[next(i for i, _ in top if chunks[i].document_id == doc)].tenant_id not in {question.context.tenant_id, "public"})
        post_cases.append(EvaluationCase(
            case_id=question.case_id,
            relevant_chunk_ids=question.relevant_document_ids,
            retrieved_chunk_ids=retrieved_docs,
            cited_chunk_ids=(), should_abstain=question.should_abstain,
            did_abstain=did_abstain, leaked_chunk_ids=leaked_docs,
            technical_failure="token_budget_error" if token_budget_error else None,
        ))
        relevant = set(question.relevant_document_ids)
        first_relevant_rank = next(
            (rank for rank, document_id in enumerate(retrieved_docs, 1) if document_id in relevant),
            None,
        )
        case_details.append({
            "case_id": question.case_id,
            "should_abstain": question.should_abstain,
            "relevant_document_ids": list(question.relevant_document_ids),
            "question_token_count": question_token_counts[len(case_details)],
            "pre_rerank": pre_detail,
            "best_score": best_score,
            "did_abstain": did_abstain,
            "rejected_candidates": rejected_count,
            "technical_failure": "token_budget_error" if token_budget_error else None,
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

    props = torch.cuda.get_device_properties(0)
    report = {
        "job_id": manifest["job_id"],
        "status": "infrastructure_smoke_only",
        "result_classification": "not_a_quality_benchmark",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hardware": {
            "gpu": torch.cuda.get_device_name(0),
            "vram_gib": props.total_memory / (1024 ** 3),
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "python": platform.python_version(),
        },
        "artifacts": {
            "embedding_repo": emb_lock["repo_id"], "embedding_revision": emb_lock["revision"],
            "reranker_repo": rerank_lock["repo_id"], "reranker_revision": rerank_lock["revision"],
            "verified_embedding_files": verified_embedding,
            "verified_reranker_files": verified_reranker,
            "download_seconds": download_seconds,
        },
        "corpus": {
            "documents": len(documents), "chunks": len(chunks), "questions": len(questions),
            "independent_manual_questions": 0,
        },
        "protocol": {
            "path": "docs/ablation-protocol.md",
            "sha256": sha256(ROOT / "docs/ablation-protocol.md"),
            "dataset_path": manifest["corpus"]["questions"],
            "dataset_sha256": sha256(ROOT / manifest["corpus"]["questions"]),
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
            "truncated_pairs": None,
            "truncated_pairs_measurement": "not_instrumented_at_scoring_boundary",
            "rejected_pairs": rejected_pairs,
            "maximum_observed_pair_tokens": max(observed_lengths, default=0),
        },
        "metrics_hybrid_pre_rerank": pre_report,
        "metrics_after_rerank": post_report,
        "acl_evidence": {
            "scope": "python_prefilter_plus_canonical_authority_postfilter_before_reranking",
            "qdrant_exercised": False,
            "security_claim": "none_for_qdrant_or_complete_multitenant_system",
            "postfilter_counters": acl_barrier_totals,
        },
        "quality_gate_passed": False,
        "cases": case_details,
        "limitations": [
            "Smoke set of 10 questions; not a statistically valid model-selection benchmark.",
            "Abstention uses a provisional normalized reranker threshold of 0.5.",
            "Hybrid retrieval uses rank fusion of dense and sparse scores; Qdrant persistence is not exercised in this GPU smoke.",
            "The ACL result applies only to the Python in-memory prefilter used by this runner.",
            "Quality metrics are non-probative until the independent 100-question intermediate set and 300-question final set exist.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT), "documents": len(documents), "chunks": len(chunks),
        "questions": len(questions), "embedding_seconds": embedding_seconds,
        "reranker_seconds": reranker_seconds, "embedding_peak_gib": embedding_peak_gib,
        "reranker_peak_gib": reranker_peak_gib, "post_metrics": post_report,
    }, indent=2))


if __name__ == "__main__":
    main()
