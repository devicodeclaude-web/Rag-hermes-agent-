from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .artifact_lock import validate_artifact_lock


@dataclass(frozen=True)
class GPUJobPlan:
    job_id: str
    status: str
    gpu_model: str
    minimum_vram_gib: int
    dense_dimension: int
    embedding_max_length: int
    reranker_max_length: int
    question_max_tokens: int
    passage_max_tokens: int
    overlap_tokens: int
    special_token_reserve: int
    required_model_bytes: int
    embedding_revision: str
    reranker_revision: str


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_gpu_job(path: str | Path) -> GPUJobPlan:
    manifest = _load_json(Path(path))
    hardware = manifest["hardware"]
    models = manifest["models"]
    embedding = manifest["embedding"]
    chunking = manifest["chunking"]
    reranker = manifest["reranker"]

    if manifest.get("status") != "candidate_unexecuted":
        raise ValueError("new GPU jobs must start as candidate_unexecuted")
    if int(hardware["gpu_count"]) != 1:
        raise ValueError("the initial smoke job supports exactly one GPU")
    if int(hardware["minimum_vram_gib"]) < 1:
        raise ValueError("minimum_vram_gib must be positive")
    if int(embedding["dense_dimension"]) != 1024:
        raise ValueError("BGE-M3 dense_dimension must be 1024")
    if int(embedding["max_length"]) > 8192:
        raise ValueError("BGE-M3 max_length cannot exceed 8192")
    if int(reranker["max_length"]) > 512:
        raise ValueError("the MVP reranker budget cannot exceed 512")
    if reranker.get("truncation_policy") != "reject":
        raise ValueError("reranker truncation_policy must be reject")
    question_max_tokens = int(chunking["question_max_tokens"])
    passage_max_tokens = int(chunking["passage_max_tokens"])
    overlap_tokens = int(chunking["overlap_tokens"])
    special_token_reserve = int(chunking["special_token_reserve"])
    if min(question_max_tokens, passage_max_tokens, special_token_reserve) < 1:
        raise ValueError("token budgets must be positive")
    if overlap_tokens < 0 or overlap_tokens >= passage_max_tokens:
        raise ValueError("invalid token overlap")
    if question_max_tokens + passage_max_tokens + special_token_reserve > int(
        reranker["max_length"]
    ):
        raise ValueError("chunking contract exceeds reranker pair budget")
    expected_tokenizer = "BAAI/bge-reranker-v2-m3"
    if chunking["tokenizer"] != expected_tokenizer:
        raise ValueError(f"unexpected tokenizer: expected {expected_tokenizer}")

    embedding_lock = _load_json(Path(models["embedding_lock"]))
    reranker_lock = _load_json(Path(models["reranker_lock"]))
    validate_artifact_lock(embedding_lock)
    validate_artifact_lock(reranker_lock)
    if embedding_lock["repo_id"] != "BAAI/bge-m3":
        raise ValueError("unexpected embedding checkpoint")
    if reranker_lock["repo_id"] != "BAAI/bge-reranker-v2-m3":
        raise ValueError("unexpected reranker checkpoint")

    required_bytes = sum(
        int(item["size"])
        for lock in (embedding_lock, reranker_lock)
        for item in lock["files"]
    )
    return GPUJobPlan(
        job_id=manifest["job_id"],
        status=manifest["status"],
        gpu_model=hardware["gpu_model"],
        minimum_vram_gib=int(hardware["minimum_vram_gib"]),
        dense_dimension=int(embedding["dense_dimension"]),
        embedding_max_length=int(embedding["max_length"]),
        reranker_max_length=int(reranker["max_length"]),
        question_max_tokens=question_max_tokens,
        passage_max_tokens=passage_max_tokens,
        overlap_tokens=overlap_tokens,
        special_token_reserve=special_token_reserve,
        required_model_bytes=required_bytes,
        embedding_revision=embedding_lock["revision"],
        reranker_revision=reranker_lock["revision"],
    )
