from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from typing import Mapping, Sequence

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_fd_bytes(descriptor: int) -> bytes:
    blocks: list[bytes] = []
    os.lseek(descriptor, 0, os.SEEK_SET)
    while block := os.read(descriptor, 1024 * 1024):
        blocks.append(block)
    return b"".join(blocks)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _receipt_utc_timestamp(receipt: Mapping[str, object], field: str) -> datetime:
    value = receipt[field]
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"execution receipt {field} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"execution receipt {field} must be a valid UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"execution receipt {field} must be a UTC timestamp")
    return parsed


def validate_consumable_receipt_v2(receipt: object) -> dict[str, object]:
    if not isinstance(receipt, dict):
        raise ValueError("execution receipt must be a JSON object")
    try:
        _canonical_json_bytes(receipt)
    except (TypeError, ValueError) as exc:
        raise ValueError("execution receipt envelope must be strict JSON") from exc
    required_keys = {
        "schema_version",
        "status",
        "started_utc",
        "finished_utc",
        "command",
        "cwd",
        "environment",
        "exit_code",
        "report",
        "report_encoding",
        "report_sha256_scope",
        "report_sha256",
    }
    actual_keys = set(receipt)
    if actual_keys != required_keys:
        missing = sorted(required_keys - actual_keys)
        unknown = sorted(actual_keys - required_keys)
        raise ValueError(
            "execution receipt keys must match the v2 schema exactly; "
            f"missing={missing}, unknown={unknown}"
        )
    if receipt.get("schema_version") != "gpu_execution_receipt.v2":
        raise ValueError("execution receipt schema_version must be gpu_execution_receipt.v2")
    if receipt.get("status") != "completed":
        raise ValueError("execution receipt status must be completed")
    command = receipt["command"]
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(part, str) or not part for part in command)
    ):
        raise ValueError("execution receipt command must be a non-empty list of non-empty strings")
    cwd = receipt["cwd"]
    if not isinstance(cwd, str) or not cwd or not Path(cwd).is_absolute():
        raise ValueError("execution receipt cwd must be an absolute path string")
    environment = receipt["environment"]
    if not isinstance(environment, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in environment.items()
    ):
        raise ValueError("execution receipt environment must map strings to strings")
    started = _receipt_utc_timestamp(receipt, "started_utc")
    finished = _receipt_utc_timestamp(receipt, "finished_utc")
    if finished < started:
        raise ValueError("execution receipt finished_utc must not precede started_utc")
    if type(receipt.get("exit_code")) is not int or receipt["exit_code"] != 0:
        raise ValueError("execution receipt exit_code must be 0")
    report = receipt.get("report")
    if not isinstance(report, dict):
        raise ValueError("execution receipt report must be a JSON object")
    if receipt.get("report_encoding") != "canonical-json-utf8":
        raise ValueError("execution receipt report_encoding must be canonical-json-utf8")
    if receipt.get("report_sha256_scope") != "receipt.report canonical-json-utf8":
        raise ValueError(
            "execution receipt report_sha256_scope must be "
            "receipt.report canonical-json-utf8"
        )
    report_sha256 = receipt.get("report_sha256")
    if not isinstance(report_sha256, str) or re.fullmatch(
        r"[0-9a-fA-F]{64}", report_sha256
    ) is None:
        raise ValueError("execution receipt report_sha256 must be 64 hexadecimal characters")
    try:
        canonical_report = _canonical_json_bytes(report)
    except (TypeError, ValueError) as exc:
        raise ValueError("execution receipt report must be strict JSON") from exc
    expected_hash = hashlib.sha256(canonical_report).hexdigest()
    if report_sha256 != expected_hash:
        raise ValueError("execution receipt report_sha256 mismatch")
    return receipt


def load_consumable_receipt_v2(path: Path) -> dict[str, object]:
    try:
        receipt = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("execution receipt is not strict JSON") from exc
    return validate_consumable_receipt_v2(receipt)


def _remove_entry_at(directory_fd: int, name: str) -> None:
    try:
        entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(entry.st_mode):
        child_fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        try:
            for child_name in os.listdir(child_fd):
                _remove_entry_at(child_fd, child_name)
        finally:
            os.close(child_fd)
        os.rmdir(name, dir_fd=directory_fd)
    else:
        os.unlink(name, dir_fd=directory_fd)


def _write_json_atomic(
    results_fd: int, name: str, payload: Mapping[str, object]
) -> None:
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    temporary_name = f".{name}.{secrets.token_hex(16)}.tmp"
    temporary_fd = -1
    try:
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=results_fd,
        )
        view = memoryview(encoded)
        while view:
            written = os.write(temporary_fd, view)
            view = view[written:]
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = -1
        os.replace(
            temporary_name,
            name,
            src_dir_fd=results_fd,
            dst_dir_fd=results_fd,
        )
        os.fsync(results_fd)
    except Exception:
        if temporary_fd >= 0:
            os.close(temporary_fd)
        try:
            os.unlink(temporary_name, dir_fd=results_fd)
        except FileNotFoundError:
            pass
        raise


def _bounded_leaf_name(path: Path, approved: Path, *, label: str) -> str:
    candidate = Path(os.path.abspath(path))
    try:
        relative = candidate.relative_to(approved)
    except ValueError as exc:
        raise ValueError(
            f"{label} path must stay inside the approved results directory"
        ) from exc
    if len(relative.parts) != 1 or relative.name in {"", ".", ".."}:
        raise ValueError(f"{label} path must be a direct file in the approved results directory")
    return relative.name


def run_with_receipt(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    report_path: Path,
    receipt_path: Path,
    approved_results_directory: Path,
    protected_paths: Sequence[Path] = (),
) -> int:
    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ValueError("command must contain non-empty strings")

    approved = approved_results_directory.resolve()
    if not approved.is_dir() or approved_results_directory.is_symlink():
        raise ValueError("approved results directory must be a real directory")
    report_name = _bounded_leaf_name(report_path, approved, label="GPU report")
    receipt_name = _bounded_leaf_name(receipt_path, approved, label="execution receipt")
    if report_name == receipt_name:
        raise ValueError("report and execution receipt paths must be distinct")
    artifact_paths = {
        Path(os.path.abspath(report_path)).resolve(strict=False),
        Path(os.path.abspath(receipt_path)).resolve(strict=False),
    }
    for protected_path in protected_paths:
        if Path(os.path.abspath(protected_path)).resolve(strict=False) in artifact_paths:
            raise ValueError("report and execution receipt must not alias a protected input")

    results_fd = os.open(
        approved,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        if not stat.S_ISDIR(os.fstat(results_fd).st_mode):
            raise ValueError("approved results directory must be a real directory")

        artifact_stats = []
        for artifact_name in (report_name, receipt_name):
            try:
                artifact_stats.append(
                    os.stat(artifact_name, dir_fd=results_fd, follow_symlinks=True)
                )
            except FileNotFoundError:
                pass
        for protected_path in protected_paths:
            try:
                protected_stat = os.stat(protected_path, follow_symlinks=True)
            except FileNotFoundError:
                continue
            if any(
                (artifact_stat.st_dev, artifact_stat.st_ino)
                == (protected_stat.st_dev, protected_stat.st_ino)
                for artifact_stat in artifact_stats
            ):
                raise ValueError(
                    "report and execution receipt must not alias a protected input"
                )

        _remove_entry_at(results_fd, report_name)
        _remove_entry_at(results_fd, receipt_name)

        started = _utc_now()
        child_environment = os.environ.copy()
        child_environment.update(environment)
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=child_environment,
            check=False,
        )
        finished = _utc_now()

        report_fd = -1
        try:
            if completed.returncode == 0:
                try:
                    report_fd = os.open(
                        report_name,
                        os.O_RDONLY | os.O_NOFOLLOW,
                        dir_fd=results_fd,
                    )
                    if not stat.S_ISREG(os.fstat(report_fd).st_mode):
                        raise RuntimeError(
                            "GPU runner exited zero without a regular report artifact"
                        )
                    report_bytes = _read_fd_bytes(report_fd)
                    try:
                        decoded_report = json.loads(
                            report_bytes.decode("utf-8"),
                            parse_constant=_reject_json_constant,
                        )
                    except (UnicodeDecodeError, ValueError) as exc:
                        raise RuntimeError("GPU runner produced an invalid JSON report") from exc
                    if not isinstance(decoded_report, dict):
                        raise RuntimeError("GPU runner report must be a JSON object")
                    report_payload: Mapping[str, object] | None = decoded_report
                    report_hash: str | None = hashlib.sha256(
                        _canonical_json_bytes(report_payload)
                    ).hexdigest()
                except (FileNotFoundError, NotADirectoryError, OSError, RuntimeError) as exc:
                    _remove_entry_at(results_fd, report_name)
                    if isinstance(exc, RuntimeError):
                        raise
                    raise RuntimeError(
                        "GPU runner exited zero without a regular report artifact"
                    ) from exc
                status = "completed"
            else:
                _remove_entry_at(results_fd, report_name)
                report_payload = None
                report_hash = None
                status = "failed"

            receipt = {
                "schema_version": "gpu_execution_receipt.v2",
                "status": status,
                "started_utc": started,
                "finished_utc": finished,
                "command": list(command),
                "cwd": str(cwd.resolve()),
                "environment": dict(environment),
                "exit_code": completed.returncode,
                "report": report_payload,
                "report_encoding": (
                    "canonical-json-utf8" if report_payload is not None else None
                ),
                "report_sha256": report_hash,
                "report_sha256_scope": (
                    "receipt.report canonical-json-utf8"
                    if report_payload is not None
                    else None
                ),
            }
            _remove_entry_at(results_fd, report_name)
            _write_json_atomic(results_fd, receipt_name, receipt)
            _remove_entry_at(results_fd, report_name)
            return completed.returncode
        except Exception:
            _remove_entry_at(results_fd, report_name)
            _remove_entry_at(results_fd, receipt_name)
            raise
        finally:
            if report_fd >= 0:
                os.close(report_fd)
    finally:
        os.close(results_fd)
