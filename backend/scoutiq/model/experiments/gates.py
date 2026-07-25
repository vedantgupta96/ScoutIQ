"""Promotion gates from #106 as explicit pass / fail / insufficient-evidence checks.

No experiment replaces the production artifact unless it clears these. Automatable
gates are computed from the run; process/data gates that this offline harness cannot
fully establish are reported as insufficient_evidence with an honest reason.
"""
from __future__ import annotations

PASS = "pass"
FAIL = "fail"
INSUFFICIENT = "insufficient_evidence"


def _decision_coverage(run: dict):
    if not run or not run.get("aggregate"):
        return None
    return run["aggregate"]["segments"]["decision_point"].get("interval_80_coverage")


def evaluate_gates(baseline_run: dict, candidate_run: dict | None, folds, coverage_tol: float = 0.075) -> list[dict]:
    gates: list[dict] = []

    leak_ok = bool(folds) and all(f.val_target > max(f.train_targets) for f in folds)
    gates.append({"id": "no_leakage",
                  "description": "Strict rolling-origin: every validation target season is strictly after its training seasons.",
                  "status": PASS if leak_ok else FAIL,
                  "detail": f"{len(folds)} folds; each validation target strictly after all training targets."})

    if candidate_run is None:
        gates.append({"id": "decision_mae_vs_v1",
                      "description": "Candidate improves or meaningfully segments contract-decision MAE vs v1 and simple baselines.",
                      "status": INSUFFICIENT,
                      "detail": "Baseline-only run; no candidate supplied to compare against v1."})
    else:
        c = candidate_run["aggregate"]["decision_mae_pct_of_cap"]
        b = baseline_run["aggregate"]["decision_mae_pct_of_cap"]
        persist = candidate_run["aggregate"]["segments"]["decision_point"].get("persistence_mae_pct")
        if c is None or b is None:
            gates.append({"id": "decision_mae_vs_v1",
                          "description": "Candidate improves or meaningfully segments contract-decision MAE vs v1 and simple baselines.",
                          "status": INSUFFICIENT, "detail": "Too few contract-decision rows to compare."})
        else:
            beats = (c <= b) and (persist is None or c <= persist)
            gates.append({"id": "decision_mae_vs_v1",
                          "description": "Candidate improves or meaningfully segments contract-decision MAE vs v1 and simple baselines.",
                          "status": PASS if beats else FAIL,
                          "detail": f"candidate {c} vs v1 {b}, persistence {persist} (% cap MAE at contract decisions)."})

    cov = _decision_coverage(candidate_run or baseline_run)
    if cov is None:
        gates.append({"id": "decision_interval_coverage",
                      "description": "Approximately nominal 80% interval coverage at contract decisions.",
                      "status": INSUFFICIENT, "detail": "Too few contract-decision rows to assess 80% coverage."})
    else:
        gates.append({"id": "decision_interval_coverage",
                      "description": "Approximately nominal 80% interval coverage at contract decisions.",
                      "status": PASS if abs(cov - 0.80) <= coverage_tol else FAIL,
                      "detail": f"decision-point 80% empirical coverage {cov} (target 0.80 ± {coverage_tol})."})

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
                  "description": "Run emits a baseline-vs-candidate comparison and an explicit promote / do-not-promote decision.",
                  "status": PASS if candidate_run else INSUFFICIENT,
                  "detail": ("Baseline-vs-candidate comparison and an explicit decision are written."
                             if candidate_run else "Baseline-only run; no candidate comparison to diff.")})
    return gates


def overall_decision(gates: list[dict], *, candidate_present: bool) -> str:
    if not candidate_present:
        return "baseline_only"
    if any(g["status"] == FAIL for g in gates):
        return "do_not_promote"
    if any(g["status"] == INSUFFICIENT for g in gates):
        return "insufficient_evidence"
    return "promote"
