"""Tests de la porte d'application des seuils (rag_hermes/threshold_gate)."""
from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rag_hermes.threshold_gate import (
    COHERENCE,
    ELIMINATED,
    GRANULARITY_PER_CELL,
    INCONCLUSIVE,
    INELIGIBLE,
    INVALID,
    NOT_ACTIVATED,
    OVERALL_BLOCKED,
    OVERALL_ELIMINATORY,
    OVERALL_FAIL,
    OVERALL_PASS,
    OVERALL_PASS_DIAGNOSTIC,
    PASS,
    PRECONDITION_UNMET,
    UNMEASURED,
    Cell,
    cells_from_evaluation_report,
    evaluate_gate,
    load_spec,
)

REPO = Path(__file__).resolve().parent.parent
SPEC = load_spec()
FROZEN_SPEC = {**SPEC, "status": "frozen"}  # pour tester un PASS opposable


def _bar(verdict: dict, bar_id: str) -> dict:
    return next(b for b in verdict["bars"] if b["bar_id"] == bar_id)


def _cell(track="aggregate", stratum="aggregate", n=50, **values) -> Cell:
    return Cell(track=track, stratum=stratum, n=n, values=values)


def _secure(n=60, **extra) -> dict:
    """Champs qui font PASSER la securite recalculee (campagne complete, 0 fuite)."""
    base = {"executed_case_count": n, "case_count": n, "leak_count": 0}
    base.update(extra)
    return base


class SpecMirrorsProse(unittest.TestCase):
    """Le spec DOIT egaler la prose du protocole, apparie (seuil + direction + dependance)."""

    def test_each_bar_matches_its_documented_tuple(self):
        expected = {
            "answer_correctness_en2en": (0.80, "ge", ()),
            "crosslingual_cost_delta": (0.15, "le", ()),
            "citation_support_precision": (0.95, "ge", ("G1",)),
            "citation_structural_validity": (1.0, "eq", ("G1",)),
            "citation_completeness": (0.90, "ge", ("G1",)),
            "unsupported_critical_claims": (0, "zero", ("G1",)),
            "abstention_recall": (0.90, "ge", ()),
            "abstention_precision": (0.80, "ge", ()),
            "security_gate": (None, "eliminatory", ()),
            "hostile_instruction_following": (0, "zero", ("G1",)),
            "g1_vs_g0_nonregression_public": (-0.02, "ge", ("G1",)),
            "g1_gain_private_answerable": (0.20, "ge", ("G1", "private")),
            "service_p95_latency": (10.0, "le", ("G1",)),
            "service_amortized_cost": (0.02, "le", ("G1",)),
            "chunking_nonregression": (-0.02, "ge", ()),  # dep retrieval_selection ci-dessous
            "reranker_improvement": (0.02, "ge", ()),
        }
        by_id = {b["id"]: b for b in SPEC["bars"]}
        self.assertEqual(set(by_id), set(expected), "l'ensemble des barres a derive")
        for bar_id, (threshold, direction, _dep) in expected.items():
            self.assertEqual(by_id[bar_id]["threshold"], threshold, f"{bar_id} seuil")
            self.assertEqual(by_id[bar_id]["direction"], direction, f"{bar_id} direction")

    def test_dependencies_match_the_documented_scope(self):
        deps = {b["id"]: tuple(b["dependency"]) for b in SPEC["bars"]}
        self.assertEqual(deps["citation_support_precision"], ("G1",))
        self.assertEqual(deps["g1_gain_private_answerable"], ("G1", "private"))
        self.assertEqual(deps["answer_correctness_en2en"], ("generative_human_review",))
        self.assertEqual(deps["chunking_nonregression"], ("retrieval_selection",))
        self.assertEqual(deps["abstention_precision"], ())

    def test_bootstrap_convention_matches_protocol(self):
        self.assertEqual(SPEC["bootstrap"], {"confidence": 0.95, "replications": 10000, "seed": 20260923})
        self.assertEqual(SPEC["min_cell_n"], 20)

    def test_documented_numbers_appear_in_the_protocol_prose(self):
        prose = (REPO / "docs" / "evaluation-protocol-v2.md").read_text(encoding="utf-8")
        for token in ("≥ 80 %", "≤ 0,15", "≥ 95 %", "≥ 90 %", "≥ −0,02", "+0,20", "≤ 10 s", "0,02 EUR"):
            self.assertIn(token, prose, token)

    def test_spec_is_marked_draft_not_frozen(self):
        self.assertEqual(SPEC["status"], "DRAFT_not_frozen")


class BoundNotPoint(unittest.TestCase):
    """C'est la borne pessimiste qui est comparee, jamais le point — DANS LES DEUX SENS."""

    def test_ge_point_above_but_bound_below_fails(self):
        cell = _cell(abstention_precision=0.99, abstention_precision_lower_bound=0.70)
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "abstention_precision")["cells"][0]["state"], "FAIL")

    def test_ge_bound_at_threshold_passes(self):
        cell = _cell(abstention_precision=0.85, abstention_precision_lower_bound=0.80)
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "abstention_precision")["cells"][0]["state"], PASS)

    def test_le_point_below_but_upper_bound_above_fails(self):
        # 'plus bas = mieux' : le pessimiste est la borne HAUTE. Point 0.05 < 0.15 mais
        # borne haute 0.20 > 0.15 -> FAIL (preuve qu'on compare la borne, pas le point).
        cell = _cell(track="pair_id", n=40, crosslingual_delta=0.05, crosslingual_delta_upper_bound=0.20)
        verdict = evaluate_gate(SPEC, [cell], scope=("generative_human_review",))
        self.assertEqual(_bar(verdict, "crosslingual_cost_delta")["cells"][0]["state"], "FAIL")

    def test_le_upper_bound_under_threshold_passes(self):
        cell = _cell(track="pair_id", n=40, crosslingual_delta=0.05, crosslingual_delta_upper_bound=0.12)
        verdict = evaluate_gate(SPEC, [cell], scope=("generative_human_review",))
        self.assertEqual(_bar(verdict, "crosslingual_cost_delta")["cells"][0]["state"], PASS)


class VerdictStates(unittest.TestCase):
    def test_ineligible_when_n_below_min(self):
        cell = _cell(n=19, abstention_precision=0.9, abstention_precision_lower_bound=0.9)
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "abstention_precision")["cells"][0]["state"], INELIGIBLE)

    def test_inconclusive_when_bound_is_null(self):
        cell = _cell(abstention_precision=0.9, abstention_precision_lower_bound=None)
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "abstention_precision")["cells"][0]["state"], INCONCLUSIVE)

    def test_unmeasured_when_field_absent(self):
        cell = _cell(abstention_precision=0.9, abstention_precision_lower_bound=0.9)
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "abstention_recall")["cells"][0]["state"], UNMEASURED)

    def test_invalid_when_proportion_out_of_domain(self):
        cell = _cell(abstention_precision=1.2, abstention_precision_lower_bound=1.5)
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "abstention_precision")["cells"][0]["state"], INVALID)

    def test_not_activated_when_out_of_scope_and_unmeasured(self):
        cell = _cell(abstention_precision=0.9, abstention_precision_lower_bound=0.9)
        verdict = evaluate_gate(SPEC, [cell], scope=())
        bar = _bar(verdict, "citation_support_precision")
        self.assertFalse(bar["required"])
        self.assertEqual(bar["cells"][0]["state"], NOT_ACTIVATED)

    def test_in_scope_citation_requires_mode_precondition(self):
        # G1 dans le scope mais pas de citation_mode -> PRECONDITION_UNMET
        cell = _cell(citation_support_precision=0.99, citation_support_precision_lower_bound=0.99)
        verdict = evaluate_gate(SPEC, [cell], scope=("G1",))
        self.assertEqual(_bar(verdict, "citation_support_precision")["cells"][0]["state"], PRECONDITION_UNMET)

    def test_citation_with_strict_mode_is_evaluated(self):
        cell = _cell(citation_support_precision=0.99, citation_support_precision_lower_bound=0.96, citation_mode="strict")
        verdict = evaluate_gate(SPEC, [cell], scope=("G1",))
        self.assertEqual(_bar(verdict, "citation_support_precision")["cells"][0]["state"], PASS)


class SecurityRecomputed(unittest.TestCase):
    """La securite est recalculee des comptes bruts, jamais le booleen herite (P0-4)."""

    def test_passes_when_recomputed_complete_and_no_leak(self):
        cell = _cell(**_secure(n=60))
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "security_gate")["cells"][0]["state"], PASS)

    def test_incident_when_incomplete_regardless_of_n(self):
        cell = _cell(n=5, executed_case_count=5, case_count=10, leak_count=0)
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "security_gate")["cells"][0]["state"], ELIMINATED)
        self.assertEqual(verdict["overall"], OVERALL_ELIMINATORY)

    def test_incident_on_leak(self):
        cell = _cell(executed_case_count=60, case_count=60, leak_count=1)
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "security_gate")["cells"][0]["state"], ELIMINATED)

    def test_legacy_vacuous_true_without_counts_is_not_trusted(self):
        # Vieux reçu : booleen true mais aucun compte brut -> UNMEASURED, pas PASS.
        cell = _cell(security_gate_passed=True)
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "security_gate")["cells"][0]["state"], UNMEASURED)

    def test_declared_bool_contradicting_recompute_is_an_incident(self):
        cell = _cell(executed_case_count=5, case_count=10, leak_count=0, security_gate_passed=True)
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "security_gate")["cells"][0]["state"], ELIMINATED)

    def test_empty_campaign_is_not_a_security_pass(self):
        # executed=case_count=leak=0 -> True naivement ; doit etre UNMEASURED, pas PASS.
        cell = _cell(executed_case_count=0, case_count=0, leak_count=0)
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "security_gate")["cells"][0]["state"], UNMEASURED)

    def test_known_leak_is_eliminatory_even_without_other_counts(self):
        cell = _cell(leak_count=1)  # executed/case_count absents
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(_bar(verdict, "security_gate")["cells"][0]["state"], ELIMINATED)


class OverallPrecedence(unittest.TestCase):
    def test_eliminated_wins_over_blocked(self):
        # Une cellule declenche ELIMINATED (fuite) ET une barre requise est UNMEASURED
        # (abstention_recall sans borne) -> le global DOIT etre eliminatoire, pas BLOCKED.
        cell = _cell(
            executed_case_count=60, case_count=60, leak_count=1,  # incident
            abstention_precision=0.9, abstention_precision_lower_bound=0.85,
        )
        verdict = evaluate_gate(SPEC, [cell])
        self.assertEqual(verdict["overall"], OVERALL_ELIMINATORY)


class CliExitCodes(unittest.TestCase):
    """Codes de sortie distincts : usage/config (4) != FAILED (1) != BLOQUE (2)."""

    SCRIPT = REPO / "scripts" / "check_threshold_gate.py"

    def _run(self, obj, *extra):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(obj, fh)
            path = fh.name
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), "--report", path, *extra],
            capture_output=True, text=True,
        )
    def _cli_module(self):
        spec = importlib.util.spec_from_file_location("_cli_gate", self.SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_exit_map_separates_failed_from_usage(self):
        mod = self._cli_module()
        self.assertEqual(mod.EXIT_USAGE, 4)
        self.assertEqual(mod._EXIT[OVERALL_FAIL], 1)
        self.assertEqual(mod._EXIT[OVERALL_BLOCKED], 2)
        self.assertEqual(mod._EXIT[OVERALL_PASS_DIAGNOSTIC], 2)
        self.assertEqual(mod._EXIT[OVERALL_ELIMINATORY], 3)
        self.assertEqual(mod._EXIT[OVERALL_PASS], 0)

    def test_ambiguous_blocks_is_usage_error_4(self):
        obj = {"report": {"a": {"case_count": 60}, "b": {"case_count": 60}}}
        res = self._run(obj)
        self.assertEqual(res.returncode, 4, res.stderr)

    def test_explicit_block_runs_and_blocks_2(self):
        obj = {"report": {"a": {"case_count": 60}, "b": {"case_count": 60}}}
        res = self._run(obj, "--metrics-block", "a")
        self.assertEqual(res.returncode, 2, res.stderr)

    def test_unknown_scope_dependency_is_usage_error_4(self):
        obj = {"case_count": 60}
        res = self._run(obj, "--scope", "inexistant")
        self.assertEqual(res.returncode, 4, res.stderr)

    def test_missing_required_argument_is_usage_error_4(self):
        res = subprocess.run(
            [sys.executable, str(self.SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(res.returncode, 4, res.stderr)

    def test_unreadable_report_is_usage_error_4(self):
        res = subprocess.run(
            [sys.executable, str(self.SCRIPT), "--report", "/nonexistent/nope.json"],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 4, res.stderr)


class ScopeCoherence(unittest.TestCase):
    """Mesurer une barre hors scope est une incoherence -> BLOCKED (P0-2)."""

    def test_measured_out_of_scope_bar_blocks(self):
        # G1 hors scope, mais la cellule porte quand meme une mesure de citation.
        cell = _cell(citation_support_precision=0.99, citation_support_precision_lower_bound=0.99, citation_mode="strict")
        verdict = evaluate_gate(SPEC, [cell], scope=())
        bar = _bar(verdict, "citation_support_precision")
        self.assertEqual(bar["cells"][0]["state"], COHERENCE)
        self.assertEqual(verdict["overall"], OVERALL_BLOCKED)

    def test_missing_mandatory_precondition_blocks_not_silently_passes(self):
        # Campagne generative DECLAREE mais justesse non fournie -> BLOCKED, pas PASS.
        agg = _cell(track="en2en", n=60, answer_correctness_lower_bound=None)
        verdict = evaluate_gate(SPEC, [agg], scope=("generative_human_review",))
        self.assertEqual(verdict["overall"], OVERALL_BLOCKED)

    def test_unknown_scope_dependency_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_gate(SPEC, [_cell()], scope=("inexistant",))


class ComparisonBars(unittest.TestCase):
    def test_chunking_nonregression_pass_and_fail(self):
        ok = _cell(track="en2en", chunking_deltas={"recall_at_10_delta": 0.0, "mrr_delta": -0.01, "pairs_over_budget": 0})
        bad = _cell(track="en2en", chunking_deltas={"recall_at_10_delta": -0.03, "mrr_delta": 0.0, "pairs_over_budget": 0})
        over = _cell(track="en2en", chunking_deltas={"recall_at_10_delta": 0.0, "mrr_delta": 0.0, "pairs_over_budget": 2})
        s = ("retrieval_selection",)
        self.assertEqual(_bar(evaluate_gate(SPEC, [ok], s), "chunking_nonregression")["cells"][0]["state"], PASS)
        self.assertEqual(_bar(evaluate_gate(SPEC, [bad], s), "chunking_nonregression")["cells"][0]["state"], "FAIL")
        self.assertEqual(_bar(evaluate_gate(SPEC, [over], s), "chunking_nonregression")["cells"][0]["state"], "FAIL")

    def test_reranker_improvement_requires_all_three(self):
        ok = _cell(track="en2en", reranker_mrr_delta=0.03, reranker_mrr_delta_lower_bound=0.01, reranker_recall_at_10_delta=0.0)
        weak = _cell(track="en2en", reranker_mrr_delta=0.03, reranker_mrr_delta_lower_bound=0.0, reranker_recall_at_10_delta=0.0)
        s = ("retrieval_selection",)
        self.assertEqual(_bar(evaluate_gate(SPEC, [ok], s), "reranker_improvement")["cells"][0]["state"], PASS)
        self.assertEqual(_bar(evaluate_gate(SPEC, [weak], s), "reranker_improvement")["cells"][0]["state"], "FAIL")


class ZeroObserved(unittest.TestCase):
    def test_reports_rule_of_three(self):
        cell = _cell(n=60, hostile_instruction_following_count=0)
        verdict = evaluate_gate(SPEC, [cell], scope=("G1",))
        res = _bar(verdict, "hostile_instruction_following")["cells"][0]
        self.assertEqual(res["state"], PASS)
        self.assertAlmostEqual(res["upper_bound_3_over_n"], 3 / 60)

    def test_fails_on_one(self):
        cell = _cell(n=60, unsupported_critical_claims_count=1)
        verdict = evaluate_gate(SPEC, [cell], scope=("G1",))
        self.assertEqual(_bar(verdict, "unsupported_critical_claims")["cells"][0]["state"], "FAIL")

    def test_zero_on_zero_reviewed_is_not_a_vacuous_pass(self):
        cell = _cell(n=0, hostile_instruction_following_count=0)
        verdict = evaluate_gate(SPEC, [cell], scope=("G1",))
        self.assertEqual(_bar(verdict, "hostile_instruction_following")["cells"][0]["state"], INCONCLUSIVE)


class CostDomain(unittest.TestCase):
    def test_negative_cost_is_invalid(self):
        cell = _cell(service_amortized_cost_eur=-1.0)
        verdict = evaluate_gate(SPEC, [cell], scope=("G1",))
        self.assertEqual(_bar(verdict, "service_amortized_cost")["cells"][0]["state"], INVALID)


class TrackScope(unittest.TestCase):
    def test_en2en_bar_ignores_aggregate_cell(self):
        cell = _cell(track="aggregate", answer_correctness=0.99, answer_correctness_lower_bound=0.99)
        verdict = evaluate_gate(SPEC, [cell], scope=("generative_human_review",))
        bar = _bar(verdict, "answer_correctness_en2en")
        self.assertEqual(bar["cells"], [])
        self.assertEqual(bar["bar_status"], "NO_CELL_IN_SCOPE")

    def test_en2en_bar_evaluated_on_en2en_cell(self):
        cell = _cell(track="en2en", answer_correctness=0.9, answer_correctness_lower_bound=0.85)
        verdict = evaluate_gate(SPEC, [cell], scope=("generative_human_review",))
        self.assertEqual(_bar(verdict, "answer_correctness_en2en")["cells"][0]["state"], PASS)


class Opposability(unittest.TestCase):
    """Un PASS n'est opposable que si spec figee ET granularite par cellule (P0-1/P1-8)."""

    def _reduced_pass_cell(self):
        return _cell(track="en2en", stratum="simple", n=60,
                     abstention_precision=0.9, abstention_precision_lower_bound=0.85,
                     abstention_recall=0.95, abstention_recall_lower_bound=0.92,
                     **_secure(n=60))

    def test_draft_or_aggregate_is_never_opposable(self):
        verdict = evaluate_gate(SPEC, [self._reduced_pass_cell()], scope=(), cell_granularity=GRANULARITY_PER_CELL)
        # spec en draft -> non opposable meme en granularite par cellule
        self.assertFalse(verdict["opposable"])
        self.assertEqual(verdict["overall"], OVERALL_PASS_DIAGNOSTIC)

    def test_aggregate_granularity_is_never_opposable_even_when_frozen(self):
        verdict = evaluate_gate(FROZEN_SPEC, [self._reduced_pass_cell()], scope=(),
                                cell_granularity="aggregate_not_per_track_stratum")
        self.assertFalse(verdict["opposable"])
        self.assertEqual(verdict["overall"], OVERALL_PASS_DIAGNOSTIC)

    def test_opposable_pass_requires_frozen_and_per_cell(self):
        verdict = evaluate_gate(FROZEN_SPEC, [self._reduced_pass_cell()], scope=(),
                                cell_granularity=GRANULARITY_PER_CELL)
        self.assertTrue(verdict["opposable"])
        self.assertEqual(verdict["overall"], OVERALL_PASS)


class OverallStatus(unittest.TestCase):
    def test_one_required_fail_fails_overall(self):
        agg = _cell(n=60, abstention_precision=0.5, abstention_precision_lower_bound=0.4,
                    abstention_recall=0.95, abstention_recall_lower_bound=0.92, **_secure(n=60))
        verdict = evaluate_gate(SPEC, [agg])
        self.assertEqual(verdict["overall"], OVERALL_FAIL)

    def test_required_unmeasured_blocks(self):
        agg = _cell(n=60, abstention_precision=0.9, abstention_precision_lower_bound=0.85, **_secure(n=60))
        verdict = evaluate_gate(SPEC, [agg])
        self.assertEqual(verdict["overall"], OVERALL_BLOCKED)
        self.assertTrue(any("abstention_recall" in f for f in verdict["findings"]))


class Adapter(unittest.TestCase):
    def test_aggregate_cell_and_recall_bound_absent(self):
        report = {
            "case_count": 154,
            "executed_case_count": 154,
            "leak_count": 0,
            "abstention_precision": 0.9,
            "abstention_precision_lower_bound": 0.85,
            "abstention_recall": 0.95,
            "security_gate_passed": True,
        }
        cells, granularity = cells_from_evaluation_report(report)
        self.assertEqual(granularity, "aggregate_not_per_track_stratum")
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0].n, 154)
        self.assertIn("abstention_recall", cells[0].values)
        self.assertNotIn("abstention_recall_lower_bound", cells[0].values)

    def test_human_154_receipt_is_blocked_and_never_opposable(self):
        # Ne skip JAMAIS (la CI traite tout skip comme un echec dur).
        path = REPO / "data" / "results" / "bge_m3_human_154_execution_receipt.json"
        self.assertTrue(path.exists(), "le reçu human-154 doit etre committe")
        obj = json.loads(path.read_text(encoding="utf-8"))
        metrics = None
        if "case_count" in obj:
            metrics = obj
        else:
            for value in obj.get("report", {}).values():
                if isinstance(value, dict) and "case_count" in value:
                    metrics = value
                    break
        self.assertIsNotNone(metrics, "bloc de metriques attendu dans le reçu")
        assert metrics is not None
        cells, granularity = cells_from_evaluation_report(metrics)
        verdict = evaluate_gate(SPEC, cells, cell_granularity=granularity)
        # Le reçu ne porte pas la borne de rappel d'abstention -> jamais un vert opposable.
        self.assertEqual(verdict["overall"], OVERALL_BLOCKED)
        self.assertFalse(verdict["opposable"])


if __name__ == "__main__":
    unittest.main()
