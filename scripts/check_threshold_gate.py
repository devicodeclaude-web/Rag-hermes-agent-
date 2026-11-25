#!/usr/bin/env python3
"""Porte CLI : compare les bornes mesurees d'un rapport aux seuils du protocole v2.

Usage :
    PYTHONPATH=. python scripts/check_threshold_gate.py \
        --report data/results/<rapport>.json \
        [--scope G1 private] [--metrics-block <cle>] [--min-n 20] [--spec <chemin>]

Le rapport attendu est un bloc de metriques EvaluationReport (asdict) : soit
directement l'objet (il porte `case_count`), soit sous `metrics`, soit un reçu v2
dont `report` contient plusieurs blocs — dans ce cas `--metrics-block <cle>` est
OBLIGATOIRE (pas de selection implicite du premier bloc).

`--scope` declare les dependances OBLIGATOIRES de ce run (G1, private,
generative_human_review, retrieval_selection). Une barre dans le scope dont la
preuve manque -> BLOCKED ; hors scope mais mesuree -> incoherence -> BLOCKED.

Exit : 0 = PASS OPPOSABLE (spec figee + granularite par cellule) ; 2 = BLOQUE ou
PASS diagnostique NON opposable (jamais pris pour un succes) ; 1 = FAILED ;
3 = eliminatoire (incident de securite).
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
    OVERALL_PASS_DIAGNOSTIC,
    cells_from_evaluation_report,
    evaluate_gate,
    load_spec,
)

_EXIT = {
    OVERALL_PASS: 0,
    OVERALL_PASS_DIAGNOSTIC: 2,  # jamais exit 0 : non opposable
    OVERALL_FAIL: 1,
    OVERALL_BLOCKED: 2,
    OVERALL_ELIMINATORY: 3,
}


def _metrics_blocks(obj: dict) -> dict[str, dict]:
    """Tous les blocs candidats portant case_count, indexes par cle."""
    if "case_count" in obj:
        return {"<racine>": obj}
    metrics = obj.get("metrics")
    if isinstance(metrics, dict) and "case_count" in metrics:
        return {"metrics": metrics}
    report = obj.get("report")
    blocks: dict[str, dict] = {}
    if isinstance(report, dict):
        for key, value in report.items():
            if isinstance(value, dict) and "case_count" in value:
                blocks[key] = value
    return blocks


def _extract_metrics(obj: dict, requested: str | None) -> dict:
    blocks = _metrics_blocks(obj)
    if not blocks:
        raise SystemExit("rapport illisible : aucun bloc de metriques (case_count) trouve")
    if requested is not None:
        if requested not in blocks:
            raise SystemExit(
                f"bloc '{requested}' absent ; blocs disponibles : {sorted(blocks)}"
            )
        return blocks[requested]
    if len(blocks) > 1:
        # Aucune selection implicite du premier bloc : ambiguite = refus.
        raise SystemExit(
            f"plusieurs blocs de metriques : {sorted(blocks)} ; "
            "precise --metrics-block <cle>"
        )
    return next(iter(blocks.values()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--spec", type=Path, default=None)
    parser.add_argument(
        "--scope", nargs="*", default=[],
        help="dependances OBLIGATOIRES de ce run (G1, private, generative_human_review, retrieval_selection)",
    )
    parser.add_argument("--metrics-block", default=None, help="cle du bloc de metriques si pluralite")
    parser.add_argument("--min-n", type=int, default=None)
    args = parser.parse_args()

    spec = load_spec(args.spec) if args.spec else load_spec()
    obj = json.loads(args.report.read_text(encoding="utf-8"))
    metrics = _extract_metrics(obj, args.metrics_block)
    cells, granularity = cells_from_evaluation_report(metrics)

    verdict = evaluate_gate(
        spec,
        cells,
        scope=args.scope,
        min_n=args.min_n,
        cell_granularity=granularity,
    )
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return _EXIT.get(verdict["overall"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
