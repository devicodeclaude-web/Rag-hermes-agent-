"""Canonical paths for the mutable quality-candidate authoring track.

The active QA dataset and the frozen 154-case human snapshot are intentionally
not writable authoring targets. New human-authored batches are accumulated in a
separate candidate that is initially seeded byte-for-byte from the frozen
snapshot and remains pending until independent review and a new freeze.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_QA_DATASET = ROOT / "data/benchmark/dataset-v2.jsonl"
FROZEN_HUMAN_DATASET = ROOT / "data/benchmark/dataset-v2-human-154.jsonl"
QUALITY_CANDIDATE_DATASET = (
    ROOT / "data/benchmark/dataset-v2-quality-candidate.jsonl"
)
FROZEN_HUMAN_CORPUS = (
    ROOT / "data/generated/hermes_public_documents-human-154.jsonl"
)


def verify_quality_candidate_seed(
    candidate: Path = QUALITY_CANDIDATE_DATASET,
    frozen: Path = FROZEN_HUMAN_DATASET,
) -> None:
    """Refuse a candidate that does not preserve the frozen 154-case prefix."""
    if not candidate.is_file():
        raise ValueError(f"quality candidate is missing: {candidate}")
    if not frozen.is_file():
        raise ValueError(f"frozen human snapshot is missing: {frozen}")

    frozen_bytes = frozen.read_bytes()
    candidate_bytes = candidate.read_bytes()
    if not candidate_bytes.startswith(frozen_bytes):
        raise ValueError(
            "quality candidate does not preserve the frozen human snapshot prefix"
        )
