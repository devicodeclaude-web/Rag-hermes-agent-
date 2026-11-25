"""Porte d'application des seuils du protocole v2 (le cablage que le protocole
dit, deux fois au paragraphe 6, 'pas encore fait' : 'aucune porte du depot ne
compare encore une borne a un seuil').

Comparateur PUR : il prend un spec de seuils (miroir machine de
docs/evaluation-protocol-v2.md, voir manifests/gates/protocol-v2-thresholds.draft.json)
et une liste de CELLULES de mesure (piste x strate x effectif x valeurs), et rend
un verdict explicite par barre et par cellule. Il n'invente AUCUNE cellule :
- champ absent de la cellule -> UNMEASURED (trou de schema, pas un echec) ;
- borne presente mais nulle -> INCONCLUSIVE (campagne incomplete, jamais une garantie) ;
- effectif < min -> INELIGIBLE (regle d'eligibilite, sans pretendre a la puissance) ;
- dependance ([G1]/[prive]) non activee -> NOT_ACTIVATED (exclue d'un gel de portee reduite) ;
- incident de securite -> ELIMINATED, eliminatoire quel que soit n.

C'est TOUJOURS la borne pessimiste (celle qui impute les pannes) qui est comparee
au seuil, jamais le point. Les barres deterministes (validite structurelle,
securite, cout) sont comparees sans IC et ne sont pas gated par n.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_SPEC_PATH = (
    Path(__file__).resolve().parent.parent
    / "manifests"
    / "gates"
    / "protocol-v2-thresholds.draft.json"
)

# --- Etats de verdict par (barre, cellule) ---------------------------------
PASS = "PASS"
FAIL = "FAIL"
INELIGIBLE = "INELIGIBLE_n_lt_min"
INCONCLUSIVE = "INCONCLUSIVE_bound_null"
UNMEASURED = "UNMEASURED_field_absent"
NOT_ACTIVATED = "NOT_ACTIVATED_dependency"
ELIMINATED = "ELIMINATED_security_incident"

# --- Statut global ----------------------------------------------------------
OVERALL_PASS = "PASS_scope_limited"
OVERALL_FAIL = "FAILED"
OVERALL_ELIMINATORY = "FAILED_eliminatory_security_incident"
OVERALL_BLOCKED = "BLOCKED_insufficient_or_inconclusive"

_ABSENT = object()


@dataclass(frozen=True)
class Cell:
    """Une cellule de mesure (piste x strate). `values` : champ -> valeur.

    Convention cruciale : une cle ABSENTE de `values` signifie 'non mesure'
    (UNMEASURED) ; une cle PRESENTE a None signifie 'mesure mais non concluant'
    (INCONCLUSIVE). Ne jamais confondre les deux.
    """

    track: str
    stratum: str
    n: int
    values: Mapping[str, Any]


def load_spec(path: str | Path = DEFAULT_SPEC_PATH) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping) or "bars" not in data:
        raise ValueError("spec de seuils invalide")
    return dict(data)


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _field(cell: Cell, key: str | None) -> Any:
    if key is None or key not in cell.values:
        return _ABSENT
    return cell.values[key]


def _in_scope(bar: Mapping[str, Any], cell: Cell) -> bool:
    scope = bar.get("track_scope")
    if scope in (None, "all"):
        return True
    return cell.track == scope


def _bound_state(value: Any, threshold: float, direction: str) -> str:
    if value is _ABSENT:
        return UNMEASURED
    if value is None:
        return INCONCLUSIVE
    if not _finite_number(value):
        raise ValueError(f"borne non numerique: {value!r}")
    if direction == "ge":
        return PASS if value >= threshold else FAIL
    if direction == "le":
        return PASS if value <= threshold else FAIL
    raise ValueError(f"direction inconnue: {direction}")


def _evaluate_bar_cell(
    bar: Mapping[str, Any], cell: Cell, activated: frozenset[str], min_n: int
) -> dict[str, Any]:
    kind = bar["kind"]
    out: dict[str, Any] = {
        "track": cell.track,
        "stratum": cell.stratum,
        "n": cell.n,
        "threshold": bar.get("threshold"),
    }

    # Securite : eliminatoire, evaluee AVANT toute regle d'effectif.
    if kind == "security":
        value = _field(cell, bar["value_key"])
        if value is _ABSENT:
            out["state"] = UNMEASURED
        elif value is None:
            out["state"] = INCONCLUSIVE
        elif value is True:
            out["state"] = PASS
        else:
            out["state"] = ELIMINATED
        out["measured"] = None if value is _ABSENT else value
        return out

    # Dependance non activee : exclue du verdict (gel de portee reduite).
    if any(dep not in activated for dep in bar.get("dependency", [])):
        out["state"] = NOT_ACTIVATED
        return out

    # Regle d'eligibilite d'effectif (seulement pour les barres jugees par IC).
    if bar.get("n_gated") and cell.n < min_n:
        out["state"] = INELIGIBLE
        return out

    if kind in ("lower_bound_ge", "paired_lower_bound_ge"):
        value = _field(cell, bar["bound_key"])
        out["measured_bound"] = None if value is _ABSENT else value
        out["point"] = None if _field(cell, bar["value_key"]) is _ABSENT else cell.values.get(bar["value_key"])
        out["state"] = _bound_state(value, bar["threshold"], "ge")
        return out

    if kind in ("upper_bound_le", "paired_upper_bound_le"):
        value = _field(cell, bar["bound_key"])
        out["measured_bound"] = None if value is _ABSENT else value
        out["state"] = _bound_state(value, bar["threshold"], "le")
        return out

    if kind == "exact_eq":
        value = _field(cell, bar["value_key"])
        out["measured"] = None if value is _ABSENT else value
        if value is _ABSENT:
            out["state"] = UNMEASURED
        elif value is None:
            out["state"] = INCONCLUSIVE
        elif not _finite_number(value):
            raise ValueError(f"valeur exacte non numerique: {value!r}")
        else:
            out["state"] = PASS if value == bar["threshold"] else FAIL
        return out

    if kind == "zero_observed":
        value = _field(cell, bar["value_key"])
        out["measured"] = None if value is _ABSENT else value
        out["upper_bound_3_over_n"] = (3.0 / cell.n) if cell.n else None
        if value is _ABSENT:
            out["state"] = UNMEASURED
        elif value is None:
            out["state"] = INCONCLUSIVE
        elif type(value) is int and value >= 0:
            out["state"] = PASS if value == 0 else FAIL
        else:
            raise ValueError(f"compte zero-observe invalide: {value!r}")
        return out

    if kind == "cost_le":
        value = _field(cell, bar["value_key"])
        out["measured"] = None if value is _ABSENT else value
        if value is _ABSENT:
            out["state"] = UNMEASURED
        elif value is None:
            out["state"] = INCONCLUSIVE
        elif not _finite_number(value):
            raise ValueError(f"cout non numerique: {value!r}")
        else:
            out["state"] = PASS if value <= bar["threshold"] else FAIL
        return out

    if kind == "comparison_nonregression":
        deltas = _field(cell, bar["value_key"])
        out["measured"] = None if deltas is _ABSENT else deltas
        if deltas is _ABSENT:
            out["state"] = UNMEASURED
        elif deltas is None:
            out["state"] = INCONCLUSIVE
        else:
            recall_d = deltas.get("recall_at_10_delta")
            mrr_d = deltas.get("mrr_delta")
            pairs = deltas.get("pairs_over_budget")
            if not _finite_number(recall_d) or not _finite_number(mrr_d) or type(pairs) is not int:
                raise ValueError("deltas de chunking incomplets")
            ok = recall_d >= bar["threshold"] and mrr_d >= bar["threshold"] and pairs == 0
            out["state"] = PASS if ok else FAIL
        return out

    if kind == "comparison_improvement":
        point = _field(cell, bar["value_key"])
        bound = _field(cell, bar["bound_key"])
        recall_d = cell.values.get("reranker_recall_at_10_delta", _ABSENT)
        out["point"] = None if point is _ABSENT else point
        out["measured_bound"] = None if bound is _ABSENT else bound
        if point is _ABSENT or bound is _ABSENT or recall_d is _ABSENT:
            out["state"] = UNMEASURED
        elif point is None or bound is None or recall_d is None:
            out["state"] = INCONCLUSIVE
        else:
            if not all(_finite_number(v) for v in (point, bound, recall_d)):
                raise ValueError("deltas de reranker non numeriques")
            ok = point >= bar["threshold"] and bound > 0 and recall_d >= 0
            out["state"] = PASS if ok else FAIL
        return out

    raise ValueError(f"type de barre inconnu: {kind}")


def evaluate_gate(
    spec: Mapping[str, Any],
    cells: Sequence[Cell],
    activated_dependencies: Iterable[str] = (),
    min_n: int | None = None,
    cell_granularity: str | None = None,
) -> dict[str, Any]:
    """Compare chaque barre du spec a ses cellules et rend un verdict structure."""
    activated = frozenset(activated_dependencies)
    effective_min_n = int(min_n if min_n is not None else spec.get("min_cell_n", 20))

    bar_reports: list[dict[str, Any]] = []
    any_eliminated = False
    any_fail = False
    any_unconcludable_required = False

    for bar in spec["bars"]:
        dependency = list(bar.get("dependency", []))
        required = all(dep in activated for dep in dependency)
        in_scope = [cell for cell in cells if _in_scope(bar, cell)]
        cell_results = [
            _evaluate_bar_cell(bar, cell, activated, effective_min_n)
            for cell in in_scope
        ]
        states = {r["state"] for r in cell_results}

        if ELIMINATED in states:
            bar_status = ELIMINATED
            any_eliminated = True
        elif FAIL in states:
            bar_status = FAIL
            if required:
                any_fail = True
        elif not required:
            bar_status = NOT_ACTIVATED
        elif not cell_results:
            bar_status = "NO_CELL_IN_SCOPE"
            any_unconcludable_required = True
        elif states == {PASS}:
            bar_status = PASS
        else:
            # required mais au moins une cellule INELIGIBLE/INCONCLUSIVE/UNMEASURED
            bar_status = "INDETERMINATE"
            any_unconcludable_required = True

        bar_reports.append(
            {
                "bar_id": bar["id"],
                "label": bar["label"],
                "section": bar.get("section"),
                "kind": bar["kind"],
                "dependency": dependency,
                "judged": bar.get("judged"),
                "required": required,
                "bar_status": bar_status,
                "cells": cell_results,
            }
        )

    if any_eliminated:
        overall = OVERALL_ELIMINATORY
    elif any_fail:
        overall = OVERALL_FAIL
    elif any_unconcludable_required:
        overall = OVERALL_BLOCKED
    else:
        overall = OVERALL_PASS

    findings: list[str] = []
    for report in bar_reports:
        if report["required"] and any(
            c["state"] == UNMEASURED for c in report["cells"]
        ):
            findings.append(
                f"{report['bar_id']}: champ absent des cellules fournies (UNMEASURED) "
                "- la source ne porte pas encore cette mesure."
            )

    return {
        "spec_version": spec.get("spec_version"),
        "spec_status": spec.get("status"),
        "overall": overall,
        "activated_dependencies": sorted(activated),
        "min_cell_n": effective_min_n,
        "cell_granularity": cell_granularity,
        "bars": bar_reports,
        "findings": findings,
    }


def cells_from_evaluation_report(
    report: Mapping[str, Any],
) -> tuple[list[Cell], str]:
    """Adapte un bloc de metriques EvaluationReport (asdict) en UNE cellule agregee.

    Aucun rapport serialise n'est encore decoupe par piste x strate : on produit
    donc une seule cellule `aggregate`, et on le DIT (cell_granularity). On ne
    pose QUE les cles que le rapport porte reellement :
    - `abstention_recall` existe en POINT seulement ; sa borne basse n'est PAS
      portee par EvaluationReport -> on n'ajoute pas `abstention_recall_lower_bound`
      -> la barre de rappel d'abstention sera UNMEASURED (decision de conception).
    """
    values: dict[str, Any] = {}

    def put(key: str, src: str) -> None:
        if src in report:
            values[key] = report[src]

    put("abstention_precision", "abstention_precision")
    put("abstention_precision_lower_bound", "abstention_precision_lower_bound")
    put("abstention_recall", "abstention_recall")  # POINT seulement, pas de borne
    put("citation_support_precision", "citation_support_precision")
    put("citation_support_precision_lower_bound", "citation_support_precision_lower_bound")
    put("citation_validity_precision", "citation_validity_precision")
    put("security_gate_passed", "security_gate_passed")

    n = report.get("case_count")
    cell = Cell(
        track="aggregate",
        stratum="aggregate",
        n=int(n) if isinstance(n, int) else 0,
        values=values,
    )
    granularity = "aggregate_not_per_track_stratum"
    return [cell], granularity
