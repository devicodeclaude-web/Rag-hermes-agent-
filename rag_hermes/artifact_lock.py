from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def artifact_files_digest(files: list[Mapping[str, Any]]) -> str:
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_artifact_lock(lock: Mapping[str, Any]) -> str:
    files = lock.get("files")
    expected = lock.get("bundle_sha256")
    if not isinstance(files, list) or not files:
        raise ValueError("artifact lock must contain a non-empty files list")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("artifact lock must contain bundle_sha256")
    actual = artifact_files_digest(files)
    if actual != expected:
        raise ValueError(f"artifact lock digest mismatch: {actual} != {expected}")
    return actual
