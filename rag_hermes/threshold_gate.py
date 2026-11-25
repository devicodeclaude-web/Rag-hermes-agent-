"""Porte d'application des seuils du protocole v2 (le cablage que le protocole
dit, deux fois au paragraphe 6, 'pas encore fait' : 'aucune porte du depot ne
compare encore une borne a un seuil').

Comparateur PUR, durci pour ne JAMAIS certifier un vert que les preuves ne
garantissent pas. Entree : un spec de seuils (miroir machine de
docs/evaluation-protocol-v2.md) + une liste de CELLULES de mesure
(piste x strate x effectif x valeurs) + un SCOPE obligatoire declare par
l'operateur. Il n'invente AUCUNE cellule.

Principes de surete :
- Une barre dont les dependances sont TOUTES dans le scope est REQUISE ; sa preuve
  manquante -> BLOCKED, jamais exclue en silence.
- Une barre hors scope est NOT_ACTIVATED (exclue) MAIS si une cellule porte
  quand meme une mesure pour elle -> SCOPE_COHERENCE_VIOLATION -> BLOCKED
  (on a mesure sans declarer).
- C'est TOUJOURS la borne pessimiste qui est comparee : borne BASSE pour 'plus
  haut = mieux' (ge), borne HAUTE pour 'plus bas = mieux' (le).
- Securite : recalculee depuis executed/case_count/leak, jamais un booleen herite ;
  eliminatoire quel que soit n ; une contradiction booleen<->recalcul est un incident.
- Domaines numeriques valides (proportion dans [0,1], cout >= 0, compte entier >= 0...)
  -> hors domaine = INVALID -> BLOCKED.
- Un PASS n'est OPPOSABLE que si la spec est FIGEE et la granularite par
  piste x strate. Sinon : verdict diagnostique non-opposable (exit non nul).
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

GRANULARITY_PER_CELL = "per_track_stratum"

# --- Etats de verdict par (barre, cellule) ---------------------------------
PASS = "PASS"
FAIL = "FAIL"
INELIGIBLE = "INELIGIBLE_n_lt_min"
INCONCLUSIVE = "INCONCLUSIVE_bound_null"
UNMEASURED = "UNMEASURED_field_absent"
NOT_ACTIVATED = "NOT_ACTIVATED_out_of_scope"
ELIMINATED = "ELIMINATED_security_incident"
INVALID = "INVALID_measurement_out_of_domain"
COHERENCE = "SCOPE_COHERENCE_VIOLATION"
PRECONDITION_UNMET = "PRECONDITION_UNMET"

# --- Statut global ----------------------------------------------------------
OVERALL_PASS = "PASS_scope_limited"
OVERALL_PASS_DIAGNOSTIC = "PASS_DIAGNOSTIC_NON_OPPOSABLE"
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
    if "min_cell_n" not in data:
        raise ValueError("spec sans min_cell_n")
    return dict(data)


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _in_domain(value: Any, domain: str | None) -> bool:
    if domain is None:
        return True
    if domain == "count":
        return type(value) is int and value >= 0
    if not _finite_number(value):
        return False
    if domain == "unit_interval":
        return 0.0 <= value <= 1.0
    if domain == "signed_unit":
        return -1.0 <= value <= 1.0
    if domain == "nonneg":
        return value >= 0.0
    raise ValueError(f"domaine inconnu: {domain}")


def _field(cell: Cell, key: str | None) -> Any:
    if key is None or key not in cell.values:
        return _ABSENT
    return cell.values[key]


def _has_evidence(cell: Cell, bar: Mapping[str, Any]) -> bool:
    """La cellule porte-t-elle une mesure SIGNIFICATIVE (presente et non None) ?"""
    for key in (bar.get("value_key"), bar.get("bound_key")):
        value = _field(cell, key)
        if value is not _ABSENT and value is not None:
            return True
    return False


def _in_scope(bar: Mapping[str, Any], cell: Cell) -> bool:
    scope = bar.get("track_scope")
    if scope in (None, "all"):
        return True
    return cell.track == scope


def _bound_state(value: Any, threshold: float, direction: str, domain: str | None) -> str:
    if value is _ABSENT:
        return UNMEASURED
    if value is None:
        return INCONCLUSIVE
    if not _in_domain(value, domain):
        return INVALID
    if direction == "ge":
        return PASS if value >= threshold else FAIL
    if direction == "le":
        return PASS if value <= threshold else FAIL
    raise ValueError(f"direction inconnue: {direction}")


def _precondition_unmet(bar: Mapping[str, Any], cell: Cell) -> bool:
    field = bar.get("precondition_field")
    if not field:
        return False
    allowed = bar.get("precondition_allowed", [])
    value = _field(cell, field)
    return value is _ABSENT or value not in allowed


def _evaluate_bar_cell(
    bar: Mapping[str, Any], cell: Cell, required: bool, min_n: int
) -> dict[str, Any]:
    kind = bar["kind"]
    out: dict[str, Any] = {
        "track": cell.track,
        "stratum": cell.stratum,
        "n": cell.n,
        "threshold": bar.get("threshold"),
    }

    # Securite : RECALCULEE, eliminatoire, AVANT toute regle d'effectif ou de scope.
    if kind == "security":
        executed = _field(cell, "executed_case_count")
        count = _field(cell, "case_count")
        leaks = _field(cell, "leak_count")
        declared = _field(cell, "security_gate_passed")
        out["recomputed_from"] = {
            "executed_case_count": None if executed is _ABSENT else executed,
            "case_count": None if count is _ABSENT else count,
            "leak_count": None if leaks is _ABSENT else leaks,
        }
        if any(v is _ABSENT for v in (executed, count, leaks)):
            # On NE fait PAS confiance a un booleen herite sans les comptes bruts.
            out["state"] = UNMEASURED
            return out
        if not all(type(v) is int and v >= 0 for v in (executed, count, leaks)):
            out["state"] = INVALID
            return out
        recomputed = (executed == count) and (leaks == 0)
        out["recomputed_pass"] = recomputed
        # Un booleen herite qui CONTREDIT le recalcul est un signal de provenance.
        if declared is not _ABSENT and declared is not None and bool(declared) != recomputed:
            out["state"] = ELIMINATED
            out["note"] = "security_gate_passed en contradiction avec le recalcul"
            return out
        out["state"] = PASS if recomputed else ELIMINATED
        return out

    # Hors scope : exclue, SAUF si une cellule porte une mesure -> incoherence.
    if not required:
        out["state"] = COHERENCE if _has_evidence(cell, bar) else NOT_ACTIVATED
        return out

    # Precondition de mesure (ex. citations : mode strict ou fail-closed).
    if _precondition_unmet(bar, cell):
        out["state"] = PRECONDITION_UNMET
        return out

    # Regle d'eligibilite d'effectif (barres jugees par IC).
    if bar.get("n_gated") and cell.n < min_n:
        out["state"] = INELIGIBLE
        return out

    domain = bar.get("domain")

    if kind in ("lower_bound_ge", "paired_lower_bound_ge"):
        value = _field(cell, bar["bound_key"])
        out["measured_bound"] = None if value is _ABSENT else value
        out["state"] = _bound_state(value, bar["threshold"], "ge", domain)
        return out

    if kind in ("upper_bound_le", "paired_upper_bound_le"):
        value = _field(cell, bar["bound_key"])
        out["measured_bound"] = None if value is _ABSENT else value
        out["state"] = _bound_state(value, bar["threshold"], "le", domain)
        return out

    if kind == "exact_eq":
        value = _field(cell, bar["value_key"])
        out["measured"] = None if value is _ABSENT else value
        if value is _ABSENT:
            out["state"] = UNMEASURED
        elif value is None:
            out["state"] = INCONCLUSIVE
        elif not _in_domain(value, domain):
            out["state"] = INVALID
        else:
            out["state"] = PASS if value == bar["threshold"] else FAIL
        return out

    if kind == "zero_observed":
        value = _field(cell, bar["value_key"])
        out["measured"] = None if value is _ABSENT else value
        # 3/N calcule sur le nombre de cas REELLEMENT relus de cette cellule.
        out["upper_bound_3_over_n"] = (3.0 / cell.n) if cell.n > 0 else None
        if value is _ABSENT:
            out["state"] = UNMEASURED
        elif value is None:
            out["state"] = INCONCLUSIVE
        elif not _in_domain(value, "count"):
            out["state"] = INVALID
        elif cell.n <= 0:
            out["state"] = INCONCLUSIVE  # 0 observe sur 0 relu = vacuement vrai.
        else:
            out["state"] = PASS if value == 0 else FAIL
        return out

    if kind == "cost_le":
        value = _field(cell, bar["value_key"])
        out["measured"] = None if value is _ABSENT else value
        if value is _ABSENT:
            out["state"] = UNMEASURED
        elif value is None:
            out["state"] = INCONCLUSIVE
        elif not _in_domain(value, domain or "nonneg"):
            out["state"] = INVALID
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
            if (
                not _in_domain(recall_d, "signed_unit")
                or not _in_domain(mrr_d, "signed_unit")
                or type(pairs) is not int
                or pairs < 0
            ):
                out["state"] = INVALID
            else:
                ok = recall_d >= bar["threshold"] and mrr_d >= bar["threshold"] and pairs == 0
                out["state"] = PASS if ok else FAIL
        return out

    if kind == "comparison_improvement":
        point = _field(cell, bar["value_key"])
        bound = _field(cell, bar["bound_key"])
        recall_d = _field(cell, "reranker_recall_at_10_delta")
        out["point"] = None if point is _ABSENT else point
        out["measured_bound"] = None if bound is _ABSENT else bound
        if point is _ABSENT or bound is _ABSENT or recall_d is _ABSENT:
            out["state"] = UNMEASURED
        elif point is None or bound is None or recall_d is None:
            out["state"] = INCONCLUSIVE
        elif not all(_in_domain(v, "signed_unit") for v in (point, bound, recall_d)):
            out["state"] = INVALID
        else:
            ok = point >= bar["threshold"] and bound > 0 and recall_d >= 0
            out["state"] = PASS if ok else FAIL
        return out

    raise ValueError(f"type de barre inconnu: {kind}")


def evaluate_gate(
    spec: Mapping[str, Any],
    cells: Sequence[Cell],
    scope: Iterable[str] = (),
    min_n: int | None = None,
    cell_granularity: str | None = None,
) -> dict[str, Any]:
    """Compare chaque barre du spec a ses cellules et rend un verdict structure.

    `scope` : ensemble des dependances DECLAREES obligatoires pour ce run. Une
    barre est requise ssi toutes ses dependances y sont ; sa preuve manquante
    -> BLOCKED. Hors scope mais mesuree -> SCOPE_COHERENCE_VIOLATION -> BLOCKED.
    """
    declared_scope = frozenset(scope)
    known = set(spec.get("dependency_catalog", {}))
    unknown = declared_scope - known if known else frozenset()
    if unknown:
        raise ValueError(f"dependances de scope inconnues: {sorted(unknown)}")
    effective_min_n = int(min_n if min_n is not None else spec["min_cell_n"])

    bar_reports: list[dict[str, Any]] = []
    any_eliminated = False
    any_fail = False
    any_blocking = False

    for bar in spec["bars"]:
        dependency = list(bar.get("dependency", []))
        required = all(dep in declared_scope for dep in dependency)
        in_scope = [cell for cell in cells if _in_scope(bar, cell)]
        cell_results = [
            _evaluate_bar_cell(bar, cell, required, effective_min_n)
            for cell in in_scope
        ]
        states = {r["state"] for r in cell_results}

        if ELIMINATED in states:
            bar_status = ELIMINATED
            any_eliminated = True
        elif COHERENCE in states:
            bar_status = COHERENCE
            any_blocking = True
        elif FAIL in states:
            bar_status = FAIL
            if required:
                any_fail = True
        elif not required:
            bar_status = NOT_ACTIVATED
        elif not cell_results:
            bar_status = "NO_CELL_IN_SCOPE"
            any_blocking = True
        elif states == {PASS}:
            bar_status = PASS
        else:
            # required mais au moins une cellule non concluante / invalide.
            bar_status = "INDETERMINATE"
            any_blocking = True

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
    elif any_blocking:
        overall = OVERALL_BLOCKED
    else:
        overall = OVERALL_PASS

    # Un PASS n'est OPPOSABLE que si la spec est FIGEE ET la granularite par cellule.
    spec_frozen = spec.get("status") == "frozen"
    per_cell = cell_granularity == GRANULARITY_PER_CELL
    opposable = overall == OVERALL_PASS and spec_frozen and per_cell
    if overall == OVERALL_PASS and not opposable:
        overall = OVERALL_PASS_DIAGNOSTIC

    findings: list[str] = []
    for report in bar_reports:
        for cell in report["cells"]:
            state = cell["state"]
            flag = state in (ELIMINATED, COHERENCE) or (
                report["required"]
                and state in (UNMEASURED, INCONCLUSIVE, INELIGIBLE, INVALID, PRECONDITION_UNMET)
            )
            if flag:
                findings.append(
                    f"{report['bar_id']} [{cell['track']}/{cell['stratum']}]: {state}"
                )
    if not spec_frozen:
        findings.append("spec en BROUILLON (status != frozen) : aucun PASS opposable possible")
    if not per_cell:
        findings.append(
            f"granularite '{cell_granularity}' != {GRANULARITY_PER_CELL} : aucun PASS opposable possible"
        )

    return {
        "spec_version": spec.get("spec_version"),
        "spec_status": spec.get("status"),
        "overall": overall,
        "opposable": opposable,
        "declared_scope": sorted(declared_scope),
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
    donc une seule cellule `aggregate`, et on le DIT (cell_granularity). Comme la
    granularite n'est pas par cellule, AUCUN PASS opposable ne pourra en sortir.
    On ne pose QUE les cles que le rapport porte reellement ; la securite est
    laissee au RECALCUL de la porte (executed/case_count/leak), pas au booleen.
    La borne basse de RAPPEL d'abstention n'est PAS portee par EvaluationReport
    -> la barre sera UNMEASURED, jamais comparee au point.
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
    # Securite : comptes bruts pour recalcul (jamais le seul booleen).
    put("executed_case_count", "executed_case_count")
    put("case_count", "case_count")
    put("leak_count", "leak_count")
    put("security_gate_passed", "security_gate_passed")

    n = report.get("case_count")
    cell = Cell(
        track="aggregate",
        stratum="aggregate",
        n=int(n) if isinstance(n, int) else 0,
        values=values,
    )
    return [cell], "aggregate_not_per_track_stratum"
