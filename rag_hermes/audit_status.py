from __future__ import annotations

from pathlib import Path
import re

_EXIT_RE = re.compile(r"^exit_code:\s*(-?\d+)\s*$", re.MULTILINE)


def evidence_exit_code(path: Path) -> int | None:
    if not path.is_file():
        return None
    match = _EXIT_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    return int(match.group(1)) if match else None


def _history_contains_401(history: Path) -> bool:
    for path in history.rglob("*") if history.exists() else ():
        if not path.is_file():
            continue
        if "401" in path.name or "401" in path.read_text(encoding="utf-8", errors="replace"):
            return True
    return False


def derive_lot_statuses(proofs: Path, history: Path) -> dict[str, dict]:
    names = (
        "tests-ci-strict.txt",
        "lock-install.txt",
        "runtime-identity.txt",
        "dataset-v1-validation.txt",
        "acl-matrix-qdrant.txt",
    )
    codes = {name: evidence_exit_code(proofs / name) for name in names}
    history_401 = _history_contains_401(history)

    lot1_ok = all(codes[name] == 0 for name in names[:3]) and history_401
    lot2_ok = codes["tests-ci-strict.txt"] == 0
    lot3_ok = codes["dataset-v1-validation.txt"] == 0
    lot4_ok = (
        codes["tests-ci-strict.txt"] == 0
        and codes["acl-matrix-qdrant.txt"] == 0
    )
    return {
        "lot_1": {
            "status": "FERMÉ" if lot1_ok else "BLOQUÉ",
            "exit_codes": {name: codes[name] for name in names[:3]},
            "history_401_present": history_401,
            "known_limit": "GHA can prove x86_64/Python 3.12 resolution, hashes and tests; CUDA runtime remains unproved.",
        },
        "lot_2": {
            "status": "FERMÉ" if lot2_ok else "BLOQUÉ",
            "exit_codes": {"tests-ci-strict.txt": codes["tests-ci-strict.txt"]},
            "known_limit": "Hybrid dense/sparse persistence in deployed Qdrant is not proved by the local smoke.",
        },
        "lot_3": {
            "status": "FERMÉ" if lot3_ok else "BLOQUÉ",
            "exit_codes": {"dataset-v1-validation.txt": codes["dataset-v1-validation.txt"]},
            "known_limit": "Initial 20-case human control and 100-case human validation/arbitration are required.",
        },
        "lot_4": {
            "status": "FERMÉ" if lot4_ok else "BLOQUÉ",
            "exit_codes": {
                "tests-ci-strict.txt": codes["tests-ci-strict.txt"],
                "acl-matrix-qdrant.txt": codes["acl-matrix-qdrant.txt"],
            },
            "known_limit": "Local Qdrant plus in-memory canonical ACL authority is exercised; deployed persistent authority and zero risk are not proved.",
        },
    }
