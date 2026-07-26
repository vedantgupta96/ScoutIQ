"""Write the harness's machine-readable JSON and a concise Markdown comparison
report. Markdown rendering is None-safe throughout: every possibly-missing
value prints as "—" rather than raising or emitting the literal string "None".
"""
from __future__ import annotations

import json
from pathlib import Path


def _fmt(value, suffix: str = "") -> str:
    return "—" if value is None else f"{value}{suffix}"


def _season_row(label: str, s: dict) -> str:
    dp = s.get("segments", {}).get("decision_point", {})
    mid = s.get("segments", {}).get("mid_contract", {})
    return (f"| {label} | {_fmt(s.get('n'))} | {_fmt(s.get('mae_pct_of_cap'))} | "
            f"{_fmt(s.get('mae_usd'))} | {_fmt(s.get('r2'))} | {_fmt(s.get('decision_mae_pct_of_cap'))} | "
            f"{_fmt(dp.get('interval_80_coverage'))} | {_fmt(mid.get('persistence_mae_pct'))} |")


def _candidate_section(title: str, run: dict) -> list[str]:
    lines = [f"## {title}: {run['candidate']}", "",
             "| Season | n | MAE % | MAE $ | R² | Decision MAE % | DP 80% cov | Mid persistence % |",
             "|---|---|---|---|---|---|---|---|"]
    for s in run["per_season"]:
        lines.append(_season_row(s["val_target"], s))
    if run.get("aggregate"):
        lines.append(_season_row("**Aggregate (weighted)**", run["aggregate"]))
    lines.append("")
    return lines


def _cohort_lines(cohorts: dict) -> list[str]:
    lines = []
    for group_name in ("age_band", "position"):
        group = cohorts.get(group_name, {})
        lines.append(f"**{group_name}**")
        if not group:
            lines.append("- (none)")
        for key in sorted(group):
            seg = group[key]
            mae = seg.get("mae_pct_of_cap")
            mae_str = _fmt(mae) if mae is not None else "insufficient"
            lines.append(f"- {key}: n={_fmt(seg.get('n'))}, MAE%={mae_str}")
        lines.append("")
    ct = cohorts.get("contract_type", {})
    lines.append(f"**contract_type**: {ct.get('status', 'insufficient_evidence')} "
                f"({ct.get('reason', 'no trustworthy labels yet')})")
    return lines


def _to_markdown(result: dict) -> str:
    dataset = result["dataset"]
    lines = [
        "# Rolling-origin valuation backtest",
        "",
        f"harness_version: `{result['harness_version']}` · seed: `{result['seed']}` · "
        f"mode: `{result['mode']}` · reserved holdout: {result['final_holdout_seasons']} · "
        f"dataset n_rows: {dataset['n_rows']} · folds: {len(result['folds'])} · "
        f"decision: **{result['decision']}**",
        "",
        "## Folds",
        "",
        "| Validation target | Train targets (first–last) | n_val |",
        "|---|---|---|",
    ]
    per_season_by_target = {s["val_target"]: s for s in result["baseline"]["per_season"]}
    for f in result["folds"]:
        train_targets = f["train_targets"]
        span = f"{train_targets[0]}–{train_targets[-1]}" if train_targets else "—"
        n_val = per_season_by_target.get(f["val_target"], {}).get("n")
        lines.append(f"| {f['val_target']} | {span} | {_fmt(n_val)} |")
    lines.append("")

    lines += _candidate_section("Baseline", result["baseline"])

    candidate_run = result.get("candidate")
    if candidate_run:
        lines += _candidate_section("Candidate", candidate_run)
        lines += ["## Comparison (aggregate)", "",
                  f"| Metric | {result['baseline']['candidate']} | {candidate_run['candidate']} |",
                  "|---|---|---|"]
        b_agg = result["baseline"]["aggregate"]
        c_agg = candidate_run["aggregate"]
        b_dp = b_agg.get("segments", {}).get("decision_point", {})
        c_dp = c_agg.get("segments", {}).get("decision_point", {})
        lines.append(f"| MAE % | {_fmt(b_agg.get('mae_pct_of_cap'))} | {_fmt(c_agg.get('mae_pct_of_cap'))} |")
        lines.append(f"| Decision MAE % | {_fmt(b_agg.get('decision_mae_pct_of_cap'))} | "
                     f"{_fmt(c_agg.get('decision_mae_pct_of_cap'))} |")
        lines.append(f"| Decision MAE $ | {_fmt(b_agg.get('decision_mae_usd'))} | "
                     f"{_fmt(c_agg.get('decision_mae_usd'))} |")
        lines.append(f"| DP 80% coverage | {_fmt(b_dp.get('interval_80_coverage'))} | "
                     f"{_fmt(c_dp.get('interval_80_coverage'))} |")
        lines.append(f"| DP 80% half-width % | {_fmt(b_dp.get('interval_80_half_width_pct'))} | "
                     f"{_fmt(c_dp.get('interval_80_half_width_pct'))} |")
        lines.append("")

    subject = candidate_run if candidate_run else result["baseline"]
    subject_agg = subject.get("aggregate", {})
    refs = subject_agg.get("references", {})
    persistence = refs.get("prior_pay_persistence", {})
    lines += [
        "## References (aggregate)",
        "",
        f"- Mean-prediction MAE %: {_fmt(refs.get('mean_prediction_mae_pct'))}",
        f"- Prior-pay persistence: n_with_prior={_fmt(persistence.get('n_with_prior'))}, "
        f"persistence MAE%={_fmt(persistence.get('persistence_mae_pct'))}",
        f"- Calibration method: {_fmt(subject_agg.get('calibration_method'))}",
        "- The nominal-vs-empirical calibration curve is measured on contract-decision rows only.",
        "",
        "## Decision-point calibration (aggregate)",
        "",
        "| Nominal | Empirical | Half-width % |",
        "|---|---|---|",
    ]
    for cal in subject_agg.get("calibration") or []:
        lines.append(f"| {_fmt(cal.get('nominal'))} | {_fmt(cal.get('empirical'))} | "
                     f"{_fmt(cal.get('half_width_pct'))} |")
    lines += ["", "## Cohorts (aggregate)", ""]
    lines += _cohort_lines(subject_agg.get("cohorts", {}))
    lines.append("")

    lines += ["## Promotion gates", "", "| Gate | Status | Detail |", "|---|---|---|"]
    for g in result["promotion_gates"]:
        lines.append(f"| {g['id']} | {g['status']} | {g['detail']} |")
    lines.append("")

    lines += ["## Decision", "",
             f"**{result['decision']}** — " + _decision_explanation(result['decision'])]

    return "\n".join(lines) + "\n"


def _decision_explanation(decision: str) -> str:
    return {
        "baseline_only": "no candidate was supplied, so only the baseline was evaluated.",
        "promote": "the candidate cleared every automatable gate with no failures or open evidence gaps.",
        "do_not_promote": "at least one promotion gate failed.",
        "insufficient_evidence": "no gate failed, but at least one gate could not be fully evaluated by this offline harness.",
    }.get(decision, "")


def write_reports(result: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "evaluation.json"
    md_path = out_dir / "evaluation.md"
    json_path.write_text(json.dumps(result, indent=2))
    md_path.write_text(_to_markdown(result))
    return json_path, md_path
