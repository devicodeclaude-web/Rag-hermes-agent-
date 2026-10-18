from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import stat
from dataclasses import asdict
from typing import Any, Iterable, Mapping, Sequence

from .acl import AuthorizationContext, Chunk
from .benchmark import BenchmarkQuestion
from .evaluation_dataset import is_quality_eligible, validate_evaluation_case
from .evaluation_runner import RetrievedChunk, run_evaluation


_REVIEWED_STATUSES = {"validated", "arbitrated"}
_HUMAN_PROVENANCE = {
    "human_task_without_corpus_view",
    "anonymized_real_user_question",
}
_FULL_GIT_SHA = re.compile(r"[0-9a-f]{40}")


def validate_campaign_shape(
    cases: Sequence[Mapping[str, Any]],
    assignments: Mapping[str, str],
    expected: Mapping[str, Any],
) -> dict[str, int]:
    counts = {
        "cases": len(cases),
        "abstentions": sum(case.get("should_abstain") is True for case in cases),
        "calibration": 0,
        "holdout": 0,
    }
    case_ids = [str(case.get("case_id", "")) for case in cases]
    if any(not case_id for case_id in case_ids) or len(set(case_ids)) != len(case_ids):
        raise ValueError("campaign case_id values must be non-empty and unique")
    if set(assignments) != set(case_ids):
        raise ValueError("campaign assignments must cover exactly every case_id")
    for partition in assignments.values():
        if partition not in {"calibration", "holdout"}:
            raise ValueError(f"unknown campaign partition: {partition}")
        counts[partition] += 1
    expected_to_actual = {
        "expected_cases": "cases",
        "expected_abstentions": "abstentions",
        "expected_calibration": "calibration",
        "expected_holdout": "holdout",
    }
    for expected_key, actual_key in expected_to_actual.items():
        expected_value = expected.get(expected_key)
        if type(expected_value) is not int or expected_value < 0:
            raise ValueError(f"{expected_key} must be a non-negative integer")
        if counts[actual_key] != expected_value:
            raise ValueError(
                f"{expected_key} mismatch: expected {expected_value}, "
                f"observed {counts[actual_key]}"
            )
    return counts


def validate_gpu_hardware(
    actual_name: str,
    total_memory_bytes: int,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    hardware = manifest.get("hardware")
    if not isinstance(hardware, Mapping):
        raise ValueError("manifest hardware block is required")
    expected_name = str(hardware.get("gpu_model", ""))
    if actual_name != expected_name:
        raise ValueError(
            f"GPU model mismatch: expected {expected_name!r}, got {actual_name!r}"
        )
    minimum_gib = hardware.get("minimum_vram_gib")
    if not isinstance(minimum_gib, (int, float)) or isinstance(minimum_gib, bool):
        raise ValueError("minimum_vram_gib must be a finite positive number")
    minimum_gib_value = float(minimum_gib)
    if not math.isfinite(minimum_gib_value) or minimum_gib_value <= 0:
        raise ValueError("minimum_vram_gib must be a finite positive number")
    actual_gib = total_memory_bytes / (1024**3)
    if actual_gib < minimum_gib_value:
        raise ValueError(
            f"GPU VRAM below manifest minimum: {actual_gib:.3f} < {minimum_gib_value} GiB"
        )
    return {"gpu": actual_name, "vram_gib": actual_gib}


def require_code_revision(value: object) -> str:
    revision = value if isinstance(value, str) else ""
    if _FULL_GIT_SHA.fullmatch(revision) is None:
        raise ValueError("RAG_CODE_REVISION must be a 40-character lowercase Git SHA")
    return revision


def require_clean_code_revision(
    claimed_value: object,
    actual_value: object,
    porcelain_output: str,
) -> str:
    claimed = require_code_revision(claimed_value)
    actual = require_code_revision(actual_value)
    if claimed != actual:
        raise ValueError(
            "RAG_CODE_REVISION does not match checked-out HEAD: "
            f"claimed {claimed}, actual {actual}"
        )
    if porcelain_output.strip():
        raise ValueError("working tree is not clean; refusing audited GPU evaluation")
    return claimed


def read_clean_repository_revision(root: Path) -> str:
    audited_root = root.resolve()
    if not audited_root.is_dir() or root.is_symlink():
        raise ValueError("audited repository root must be a real directory")
    git_marker = audited_root / ".git"
    if git_marker.is_symlink():
        raise ValueError("audited repository root requires a real .git directory or gitfile")
    if git_marker.is_dir():
        expected_git_dir = git_marker.resolve()
    elif git_marker.is_file():
        marker = git_marker.read_text(encoding="utf-8").strip()
        if not marker.startswith("gitdir: ") or not marker[8:]:
            raise ValueError("audited repository root contains an invalid gitfile")
        expected_git_dir = (audited_root / marker[8:]).resolve()
        if not expected_git_dir.is_dir() or expected_git_dir.is_symlink():
            raise ValueError("audited repository root contains an invalid gitfile")
    else:
        raise ValueError("audited repository root requires a real .git directory or gitfile")
    git_environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    git_environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        top_level = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=audited_root, check=True,
            capture_output=True, text=True, timeout=30, env=git_environment,
        ).stdout.strip()
        actual_git_dir = subprocess.run(
            ["git", "rev-parse", "--git-dir"], cwd=audited_root, check=True,
            capture_output=True, text=True, timeout=30, env=git_environment,
        ).stdout.strip()
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=audited_root, check=True,
            capture_output=True, text=True, timeout=30, env=git_environment,
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=audited_root, check=True, capture_output=True, text=True, timeout=30,
            env=git_environment,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"unable to verify repository provenance: {exc}") from exc
    if Path(top_level).resolve() != audited_root:
        raise ValueError("audited repository root does not match Git repository root")
    resolved_git_dir = (audited_root / actual_git_dir).resolve()
    if resolved_git_dir != expected_git_dir:
        raise ValueError("audited repository git directory does not match .git marker")
    require_clean_code_revision(revision, revision, porcelain)
    return revision


def read_repository_snapshot(root: Path, path: Path) -> tuple[bytes, dict[str, str]]:
    audited_root = root.resolve()
    if not audited_root.is_dir() or root.is_symlink():
        raise ValueError("audited repository root must be a real directory")
    candidate = path if path.is_absolute() else audited_root / path
    lexical_path = Path(os.path.abspath(candidate))
    try:
        relative_path = lexical_path.relative_to(audited_root)
    except ValueError as exc:
        raise ValueError("attested file must stay inside the audited repository") from exc
    parts = relative_path.parts
    if not parts:
        raise ValueError("attested file must be a regular non-symlink file")

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | nofollow
    directory_fd = os.open(audited_root, directory_flags)
    try:
        for component in parts[:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(parts[-1], os.O_RDONLY | nofollow, dir_fd=directory_fd)
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise ValueError("attested file must be a regular non-symlink file")
            with os.fdopen(file_fd, "rb") as handle:
                file_fd = -1
                payload = handle.read()
        finally:
            if file_fd >= 0:
                os.close(file_fd)
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        raise ValueError("attested file must be a regular non-symlink file") from exc
    finally:
        os.close(directory_fd)

    return payload, {
        "path": relative_path.as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def read_repository_json_snapshot(
    root: Path,
    path: Path,
    expected_sha256: object | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    payload, attestation = read_repository_snapshot(root, path)
    if expected_sha256 is not None:
        expected = expected_sha256 if isinstance(expected_sha256, str) else ""
        if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ValueError("expected manifest SHA-256 must be 64 lowercase hex characters")
        if attestation["sha256"] != expected:
            raise ValueError(
                "manifest SHA-256 mismatch: "
                f"expected {expected}, actual {attestation['sha256']}"
            )
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError("attested JSON root must be an object")
    return decoded, attestation


def read_model_lock_snapshots(
    root: Path, manifest: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    models = manifest.get("models")
    if not isinstance(models, Mapping):
        raise ValueError("manifest models block is required")
    snapshots: dict[str, dict[str, Any]] = {}
    for name, key in (
        ("embedding", "embedding_lock"),
        ("reranker", "reranker_lock"),
    ):
        relative_path = models.get(key)
        if not isinstance(relative_path, str) or not relative_path:
            raise ValueError(f"manifest models.{key} is required")
        data, attestation = read_repository_json_snapshot(root, root / relative_path)
        snapshots[name] = {"data": data, "attestation": attestation}
    return snapshots


def repository_file_attestation(root: Path, path: Path) -> dict[str, str]:
    _payload, attestation = read_repository_snapshot(root, path)
    return attestation


def read_attested_json(path: Path, expected_sha256: object) -> dict[str, Any]:
    expected = expected_sha256 if isinstance(expected_sha256, str) else ""
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise ValueError("expected manifest SHA-256 must be 64 lowercase hex characters")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, os.O_RDONLY | nofollow)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("attested JSON must be a regular non-symlink file")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                payload = handle.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("attested JSON must be a regular non-symlink file") from exc
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValueError(f"manifest SHA-256 mismatch: expected {expected}, actual {actual}")
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError("attested JSON root must be an object")
    return decoded


def invalidate_gpu_output(
    output: Path,
    approved_results_directory: Path,
    *,
    protected_paths: Iterable[Path],
) -> None:
    approved = approved_results_directory.resolve()
    if not approved.is_dir() or approved_results_directory.is_symlink():
        raise ValueError("approved results directory must be a real directory")
    resolved_output = output.resolve(strict=False)
    for protected in protected_paths:
        protected_resolved = protected.resolve(strict=False)
        aliases = resolved_output == protected_resolved
        if output.exists() and protected.exists():
            aliases = aliases or output.samefile(protected)
        if aliases:
            raise ValueError(f"GPU output aliases a protected input: {protected}")
    if not resolved_output.is_relative_to(approved):
        raise ValueError("GPU output must stay inside the approved results directory")
    if output.is_dir() and not output.is_symlink():
        raise ValueError("GPU output path must not be a directory")
    if output.exists() or output.is_symlink():
        output.unlink()
    if output.exists() or output.is_symlink():
        raise OSError(f"failed to invalidate stale GPU output: {output}")


def publish_gpu_report_atomic(
    output: Path,
    approved_results_directory: Path,
    report: Mapping[str, Any],
) -> None:
    approved = approved_results_directory.resolve()
    if not approved.is_dir() or approved_results_directory.is_symlink():
        raise ValueError("approved results directory must be a real directory")
    candidate = output if output.is_absolute() else Path.cwd() / output
    lexical_output = Path(os.path.abspath(candidate))
    try:
        relative_output = lexical_output.relative_to(approved)
    except ValueError as exc:
        raise ValueError("GPU output must stay inside the approved results directory") from exc
    if not relative_output.parts:
        raise ValueError("GPU output path must name a file")

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(approved, os.O_RDONLY | os.O_DIRECTORY | nofollow)
    temporary_name = f".{relative_output.name}.{secrets.token_hex(12)}.tmp"
    temporary_created = False
    try:
        for component in relative_output.parts[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | nofollow,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        temporary_created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary_name,
            relative_output.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_created = False
        os.fsync(directory_fd)
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        raise ValueError("GPU output parent must be a real approved directory") from exc
    finally:
        if temporary_created:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def reranker_truncation_evidence(
    *,
    rejected_pairs: int,
    maximum_observed_pair_tokens: int,
) -> dict[str, Any]:
    if type(rejected_pairs) is not int or rejected_pairs < 0:
        raise ValueError("rejected_pairs must be a non-negative integer")
    if type(maximum_observed_pair_tokens) is not int or maximum_observed_pair_tokens < 0:
        raise ValueError("maximum_observed_pair_tokens must be a non-negative integer")
    return {
        "truncated_pairs": None,
        "truncated_pairs_measurement": (
            "not_instrumented_inside_flag_reranker_compute_score"
        ),
        "rejected_pairs": rejected_pairs,
        "maximum_observed_pair_tokens": maximum_observed_pair_tokens,
    }


def gpu_execution_metadata(
    *,
    is_human: bool,
    receipt_path: str | None,
) -> dict[str, Any]:
    if is_human and not receipt_path:
        raise ValueError("human GPU evaluation requires an external execution receipt")
    return {
        "command": None,
        "exit_code": None,
        "external_receipt": receipt_path,
        "attestation": (
            "external_launcher_after_process_exit" if is_human else "not_recorded"
        ),
        "qdrant_version": None,
        "qdrant_status": "not_exercised_in_component_runner",
    }


def gpu_report_limitations(*, is_human: bool) -> list[str]:
    if is_human:
        dataset_limit = (
            "Human set of 154 reviewed cases; the abstention threshold is selected "
            "only on the calibration partition and reported on a pair-grouped holdout."
        )
        threshold_limit = (
            "The legacy metrics_after_rerank block uses the provisional fixed "
            "threshold 0.5; confirmatory abstention metrics are in "
            "abstention_calibration.holdout."
        )
        campaign_limit = (
            "This 154-case human run is intermediate evidence; final model-selection "
            "claims remain blocked until the pre-registered 300-case set exists."
        )
    else:
        dataset_limit = (
            "Smoke set of 10 questions; not a statistically valid model-selection "
            "benchmark."
        )
        threshold_limit = (
            "Abstention uses a provisional normalized reranker threshold of 0.5."
        )
        campaign_limit = (
            "No human-campaign claim applies to this legacy infrastructure smoke."
        )
    return [
        dataset_limit,
        threshold_limit,
        (
            "Hybrid retrieval uses rank fusion of dense and sparse scores; Qdrant "
            "persistence is not exercised in this GPU smoke."
        ),
        "The ACL result applies only to the Python in-memory prefilter used by this runner.",
        campaign_limit,
    ]


def human_evidence_counts(cases: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "questions_total": len(cases),
        "independent_manual_questions": sum(
            case.get("question_provenance") in _HUMAN_PROVENANCE for case in cases
        ),
    }


def human_cases_to_questions(
    cases: Sequence[Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[BenchmarkQuestion]]:
    """Validate reviewed public human cases and adapt them for GPU retrieval."""
    validated: list[dict[str, Any]] = []
    questions: list[BenchmarkQuestion] = []
    context = AuthorizationContext(
        tenant_id="public", user_id="evaluator", groups=(), clearance=0
    )
    for raw_case in cases:
        if raw_case.get("reference_status") not in _REVIEWED_STATUSES:
            raise ValueError("GPU human evaluation requires every reference to be reviewed")
        if not is_quality_eligible(raw_case):
            raise ValueError("GPU human evaluation accepts only quality-eligible cases")
        case = validate_evaluation_case(raw_case, documents, manifest)
        if case["access_scope"] != "public":
            raise ValueError("GPU human evaluation accepts only public cases")
        relevant_document_ids = tuple(
            dict.fromkeys(str(span["document_id"]) for span in case["relevance_spans"])
        )
        validated.append(case)
        questions.append(BenchmarkQuestion(
            case_id=str(case["case_id"]),
            question=str(case["question"]),
            context=context,
            relevant_document_ids=relevant_document_ids,
            should_abstain=case["should_abstain"],
        ))
    if not validated:
        raise ValueError("at least one human evaluation case is required")
    return validated, questions


def score_human_retrieval(
    cases: Sequence[Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
    ranked_by_case: Mapping[str, Mapping[str, Any]],
    *,
    threshold: float,
    k: int,
) -> dict[str, Any]:
    def answer_fn(
        _question: str,
        case: Mapping[str, object],
    ) -> tuple[tuple[RetrievedChunk, ...], tuple[RetrievedChunk, ...], bool]:
        case_id = str(case["case_id"])
        ranked = ranked_by_case.get(case_id)
        if ranked is None:
            raise ValueError(f"missing scored retrieval for {case_id}")
        chunks = ranked.get("chunks")
        if not isinstance(chunks, (list, tuple)) or any(
            not isinstance(chunk, Chunk) for chunk in chunks
        ):
            raise ValueError(f"invalid ranked chunks for {case_id}")
        raw_score = ranked.get("best_score")
        if raw_score is None:
            best_score = None
        elif isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
            best_score = float(raw_score)
        else:
            raise ValueError(f"invalid best_score for {case_id}")
        retrieved = tuple(RetrievedChunk(chunk) for chunk in chunks)
        abstained = best_score is None or best_score < threshold
        return retrieved, (), abstained

    return asdict(run_evaluation(cases, documents, manifest, answer_fn, k=k))


def deterministic_group_split(
    cases: Sequence[Mapping[str, Any]],
    *,
    salt: str,
) -> dict[str, str]:
    """Assign whole pair groups to calibration or holdout deterministically."""
    if not salt:
        raise ValueError("salt must not be empty")
    assignments: dict[str, str] = {}
    groups: dict[str, str] = {}
    for case in cases:
        case_id = str(case.get("case_id", ""))
        if not case_id or case_id in assignments:
            raise ValueError("case_id values must be non-empty and unique")
        pair_id = case.get("pair_id")
        group_id = str(pair_id) if pair_id else case_id
        if group_id not in groups:
            digest = hashlib.sha256(f"{salt}:{group_id}".encode("utf-8")).digest()
            groups[group_id] = "calibration" if int.from_bytes(digest, "big") % 2 == 0 else "holdout"
        assignments[case_id] = groups[group_id]
    return assignments


def _validated_rows(rows: Sequence[Mapping[str, Any]]) -> list[tuple[bool, float | None]]:
    validated: list[tuple[bool, float | None]] = []
    for row in rows:
        expected = row.get("should_abstain")
        if type(expected) is not bool:
            raise ValueError("should_abstain must be a bool")
        raw_score = row.get("best_score")
        if raw_score is None:
            score = None
        elif type(raw_score) not in {int, float} or not math.isfinite(float(raw_score)):
            raise ValueError("best_score must be finite or null")
        else:
            score = float(raw_score)
        validated.append((expected, score))
    if not validated:
        raise ValueError("at least one scored case is required")
    return validated


def wilson_interval(successes: int, total: int) -> dict[str, float]:
    if type(successes) is not int or type(total) is not int:
        raise ValueError("Wilson counts must be integers")
    if total < 1 or successes < 0 or successes > total:
        raise ValueError("Wilson counts must satisfy 0 <= successes <= total")
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total
            + z * z / (4 * total * total)
        )
        / denominator
    )
    return {"level": 0.95, "low": max(0.0, centre - margin), "high": min(1.0, centre + margin)}


def score_threshold(
    rows: Sequence[Mapping[str, Any]],
    *,
    threshold: float,
) -> dict[str, Any]:
    if type(threshold) not in {int, float} or not math.isfinite(float(threshold)):
        raise ValueError("threshold must be finite")
    threshold = float(threshold)
    validated = _validated_rows(rows)
    tp = fp = tn = fn = 0
    for expected, score in validated:
        predicted = score is None or score < threshold
        if expected and predicted:
            tp += 1
        elif expected:
            fn += 1
        elif predicted:
            fp += 1
        else:
            tn += 1
    positives = tp + fn
    negatives = tn + fp
    abstention_recall = tp / positives if positives else None
    answer_recall = tn / negatives if negatives else None
    balanced_accuracy = (
        (abstention_recall + answer_recall) / 2
        if abstention_recall is not None and answer_recall is not None
        else None
    )
    return {
        "threshold": threshold,
        "cases_total": len(validated),
        "required_abstentions": positives,
        "required_answers": negatives,
        "true_positive_abstentions": tp,
        "false_positive_abstentions": fp,
        "true_negative_answers": tn,
        "false_negative_answers": fn,
        "abstention_recall": abstention_recall,
        "abstention_recall_wilson_95": (
            wilson_interval(tp, positives) if positives else None
        ),
        "answer_recall": answer_recall,
        "answer_recall_wilson_95": (
            wilson_interval(tn, negatives) if negatives else None
        ),
        "balanced_accuracy": balanced_accuracy,
    }


def calibrate_threshold(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fit a threshold on calibration rows using balanced accuracy only."""
    validated = _validated_rows(rows)
    if not any(expected for expected, _score in validated) or not any(
        not expected for expected, _score in validated
    ):
        raise ValueError("calibration requires both abstention and answerable cases")
    numeric_scores = sorted({score for _expected, score in validated if score is not None})
    if not numeric_scores:
        raise ValueError("calibration requires at least one numeric best_score")
    candidates = [numeric_scores[0]] + [
        math.nextafter(score, math.inf) for score in numeric_scores
    ]
    scored = [score_threshold(rows, threshold=candidate) for candidate in candidates]
    best = max(
        scored,
        key=lambda item: (item["balanced_accuracy"], -item["threshold"]),
    )
    return {
        "objective": "balanced_accuracy",
        "tie_break": "lowest_threshold",
        "threshold": best["threshold"],
        "candidate_count": len(candidates),
        "metrics": best,
    }
