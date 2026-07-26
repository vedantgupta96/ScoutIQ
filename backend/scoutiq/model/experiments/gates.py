"""Promotion gates from #106 as explicit pass / fail / insufficient-evidence checks.

No experiment replaces the production artifact unless it clears these. Automatable
gates are computed from the run; process/data gates that this offline harness cannot
fully establish are reported as insufficient_evidence with an honest reason.
"""
from __future__ import annotations

PASS = "pass"
FAIL = "fail"
INSUFFICIENT = "insufficient_evidence"


DECISION_MAE_GATE_DESCRIPTION = (
    "Candidate strictly improves contract-decision MAE against the v1 baseline and the "
    "decision-point mean-prediction baseline on all contract-decision rows, and against "
    "prior-pay persistence on the contract-decision rows that carry a usable prior salary "
    "(persistence's own eligible population, per #110)."
)


def evaluate_gates(baseline_run: dict, candidate_run: dict | None, folds, coverage_tol: float = 0.075) -> list[dict]:
    gates: list[dict] = []
    baseline_name = baseline_run["candidate"]

    leak_ok = bool(folds) and all(f.val_target > max(f.train_targets) for f in folds)
    gates.append({"id": "no_leakage",
                  "description": "Strict rolling-origin: every validation target season is strictly after its training seasons.",
                  "status": PASS if leak_ok else FAIL,
                  "detail": f"{len(folds)} folds; each validation target strictly after all training targets."})

    if candidate_run is None:
        gates.append({"id": "decision_mae_vs_v1",
                      "description": DECISION_MAE_GATE_DESCRIPTION,
                      "status": INSUFFICIENT,
                      "detail": "Baseline-only run; no candidate supplied to compare against v1."})
    else:
        agg = candidate_run["aggregate"]
        c = agg["decision_mae_pct_of_cap"]
        b = baseline_run["aggregate"]["decision_mae_pct_of_cap"]
        mean_ref = agg.get("decision_mean_prediction_mae_pct")
        persist = agg["segments"]["decision_point"].get("persistence_mae_pct")
        c_persist_pop = agg.get("decision_persistence_population_mae_pct")
        missing = [name for name, v in (("candidate decision MAE", c), ("baseline decision MAE", b),
                   ("decision mean-prediction", mean_ref), ("decision persistence", persist),
                   ("candidate decision MAE on usable-prior rows", c_persist_pop)) if v is None]
        if missing:
            status = INSUFFICIENT
            detail = f"insufficient contract-decision evidence (missing: {', '.join(missing)})."
        else:
            status = PASS if (c < b and c < mean_ref and c_persist_pop < persist) else FAIL
            detail = (f"candidate {c} vs {baseline_name} {b} and decision mean-prediction {mean_ref} "
                      f"on all contract-decision rows; candidate {c_persist_pop} vs persistence {persist} "
                      f"on contract-decision rows with usable prior pay "
                      f"(% cap MAE; strict improvement over all three required).")
        gates.append({"id": "decision_mae_vs_v1",
                      "description": DECISION_MAE_GATE_DESCRIPTION,
                      "status": status, "detail": detail})

    subject = candidate_run or baseline_run
    subj_agg = subject["aggregate"] if subject else {}
    cov = subj_agg.get("segments", {}).get("decision_point", {}).get("interval_80_coverage") if subj_agg else None
    method = subj_agg.get("calibration_method") if subj_agg else None
    if cov is None:
        gates.append({"id": "decision_interval_coverage",
                      "description": "Approximately nominal 80% interval coverage at contract decisions.",
                      "status": INSUFFICIENT, "detail": "Too few contract-decision rows to assess 80% coverage."})
    elif method != "decision_point_oof":
        gates.append({"id": "decision_interval_coverage",
                      "description": "Approximately nominal 80% interval coverage at contract decisions.",
                      "status": INSUFFICIENT,
                      "detail": (f"decision-point coverage {cov} was measured under '{method}' "
                                 f"calibration (fallback), not production decision-point OOF — not comparable to v1.")})
    else:
        gates.append({"id": "decision_interval_coverage",
                      "description": "Approximately nominal 80% interval coverage at contract decisions.",
                      "status": PASS if abs(cov - 0.80) <= coverage_tol else FAIL,
                      "detail": (f"decision-point 80% empirical coverage {cov} (target 0.80 ± {coverage_tol}); "
                                 f"decision-point OOF calibration.")})

    gates.append({"id": "cohort_reporting",
                  "description": "Sample size + calibration reported for age, position, contract-type, and data-coverage cohorts.",
                  "status": INSUFFICIENT,
                  "detail": "Age and position cohorts are reported per season and in aggregate; contract-type and data-coverage cohorts await trustworthy labels (#109)."})

    gates.append({"id": "methodology_documentation",
                  "description": "Feature coverage, missingness, source freshness, and methodology version documented.",
                  "status": INSUFFICIENT,
                  "detail": "Methodology version, feature set, and missingness are emitted; source freshness is owned by the Data Provenance Center and not asserted here."})

    gates.append({"id": "pct_of_cap_unit",
                  "description": "Percent of cap preserved as the cross-season money unit.",
                  "status": PASS, "detail": "All errors, references, and intervals are reported in percent of cap."})

    gates.append({"id": "graceful_degradation_adr_0001",
                  "description": "Existing valuation remains available when enrichment data is missing (ADR-0001).",
                  "status": INSUFFICIENT,
                  "detail": "Baseline/current-season candidates use no enrichment features; the ADR-0001 degrade path is exercised at production integration, not in this offline run."})

    gates.append({"id": "artifact_report_diff_and_decision",
                  "description": "An artifact/report diff and an explicit promote / do-not-promote decision are produced for review.",
                  "status": INSUFFICIENT,
                  "detail": ("A baseline-vs-candidate metric comparison and an explicit decision are emitted, but a "
                             "production model-artifact diff (weights/predictions vs the shipped model) is a "
                             "separate promotion-time step this offline run does not produce."
                             if candidate_run else
                             "Baseline-only run; no candidate comparison or decision to diff.")})
    return gates


def overall_decision(gates: list[dict], *, candidate_present: bool) -> str:
    if not candidate_present:
        return "baseline_only"
    if any(g["status"] == FAIL for g in gates):
        return "do_not_promote"
    if any(g["status"] == INSUFFICIENT for g in gates):
        return "insufficient_evidence"
    return "promote"
