#!/usr/bin/env python3
"""Vérifie que le benchmark d'éval v2 versionné correspond au lock épinglé.

Compare, pour chaque fichier figé dans `manifests/locks/benchmark-v2.lock.json`
(jeu actif `dataset-v2.jsonl`, les 3 strates dédiées et leurs fixtures), le
sha256 brut (octet pour octet) et le nombre d'enregistrements aux valeurs du
lock, puis recalcule l'empreinte agrégée `benchmark_sha`. Épingle aussi
l'invariante public-only du jeu actif (acl_probe False partout).

Usage :
    PYTHONPATH=. python3 scripts/verify_benchmark_lock.py

Sort 1 si un fichier manque, si un sha/compte diverge, si l'empreinte agrégée
diverge, ou si le jeu actif n'est plus public-only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "manifests/locks/benchmark-v2.lock.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    if not LOCK.exists():
        print(f"ÉCHEC: lock absent: {LOCK}")
        return 1
    lock = json.loads(LOCK.read_text(encoding="utf-8"))

    entries = [lock["active_dataset"], *lock["strata"], *lock["fixture_dependencies"]]
    problems: list[str] = []
    agg_parts: dict[str, str] = {}

    for entry in entries:
        rel = entry["path"]
        path = ROOT / rel
        if not path.exists():
            problems.append(f"{rel}: fichier absent")
            continue
        actual_sha = _sha256(path)
        actual_count = len(_records(path))
        agg_parts[rel] = actual_sha
        if actual_sha != entry["sha256"]:
            problems.append(f"{rel}: sha256 lock={entry['sha256']} réel={actual_sha}")
        if actual_count != entry["record_count"]:
            problems.append(f"{rel}: record_count lock={entry['record_count']} réel={actual_count}")

    # Empreinte agrégée (même construction que le gel : "chemin:sha" triés).
    agg_src = "\n".join(f"{p}:{agg_parts[p]}" for p in sorted(agg_parts))
    actual_benchmark_sha = hashlib.sha256(agg_src.encode("utf-8")).hexdigest()
    if actual_benchmark_sha != lock["benchmark_sha"]:
        problems.append(
            f"benchmark_sha lock={lock['benchmark_sha']} réel={actual_benchmark_sha}"
        )

    # Invariante public-only du jeu actif.
    active_path = ROOT / lock["active_dataset"]["path"]
    if active_path.exists():
        acl_flags = {bool(r.get("acl_probe", False)) for r in _records(active_path)}
        if acl_flags != {False}:
            problems.append(
                f"jeu actif non public-only: acl_probe doit être False partout, vu {acl_flags}"
            )

    print(f"benchmark={LOCK.name}")
    print(f"benchmark_sha={actual_benchmark_sha}")
    print(f"git_head={lock.get('git_head')}")
    if problems:
        print("\nÉCHEC VÉRIFICATION LOCK:")
        for p in problems:
            print("  -", p)
        return 1
    print("\nLOCK OK (sha256 + comptes + empreinte agrégée + public-only conformes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
