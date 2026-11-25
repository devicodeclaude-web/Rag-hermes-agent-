#!/usr/bin/env python3
"""Porte CLI : compare les bornes mesurees d'un rapport aux seuils du protocole v2.

Usage :
    PYTHONPATH=. python scripts/check_threshold_gate.py \
        --report data/results/<rapport>.json \
        [--activate G1 private] [--min-n 20] [--spec <chemin>]

Le rapport attendu est un bloc de metriques EvaluationReport (asdict) : soit
directement l'objet (il porte `case_count`), soit imbrique sous une cle `metrics`.
Exit : 0 = PASS (portee limitee aux dependances activees) ; 1 = FAILED ;
3 = eliminatoire (incident de securite) ; 2 = BLOQUE (insuffisant/non concluant).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag_hermes.threshold_gate import (  # noqa: E402
    OVERALL_BLOCKED,
    OVERALL_ELIMINATORY,
    OVERALL_FAIL,
    OVERALL_PASS,
    cells_from_evaluation_report,
    evaluate_gate,
    load_spec,
)

_EXIT = {
    OVERALL_PASS: 0,
    OVERALL_FAIL: 1,
    OVERALL_BLOCKED: 2,
    OVERALL_ELIMINATORY: 3,
}


def _extract_metrics(obj: dict) -> dict:
    if "case_count" in obj:
        return obj
    metrics = obj.get("metrics")
    if isinstance(metrics, dict) and "case_count" in metrics:
        return metrics
    # Recu v2 : report.metrics_* ; on prend le premier bloc portant case_count.
    report = obj.get("report")
    if isinstance(report, dict):
        for value in report.values():
            if isinstance(value, dict) and "case_count" in value:
                return value
    raise SystemExit(
        "rapport illisible : aucun bloc de metriques (case_count) trouve"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--spec", type=Path, default=None)
    parser.add_argument("--activate", nargs="*", default=[], help="dependances activees (G1, private)")
    parser.add_argument("--min-n", type=int, default=None)
    args = parser.parse_args()

    spec = load_spec(args.spec) if args.spec else load_spec()
    obj = json.loads(args.report.read_text(encoding="utf-8"))
    metrics = _extract_metrics(obj)
    cells, granularity = cells_from_evaluation_report(metrics)

    verdict = evaluate_gate(
        spec,
        cells,
        activated_dependencies=args.activate,
        min_n=args.min_n,
        cell_granularity=granularity,
    )
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return _EXIT.get(verdict["overall"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
