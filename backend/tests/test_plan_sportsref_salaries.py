import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scoutiq.etl import plan_sportsref_salaries as plan_mod
from scoutiq.etl.plan_sportsref_salaries import DbState, NameCandidate, StoredContract, build_plan, take_snapshot
from scoutiq.sources.sportsref_salary_export import parse_export

FIXTURE = Path(__file__).parent / "fixtures" / "sportsref" / "contracts_export.html"


@pytest.fixture(scope="module")
def parsed():
    return parse_export(FIXTURE.read_text(encoding="utf-8"))


def _state(**kw):
    base = dict(
        verified_xref={"jamesle01": [23], "tatumja01": [30], "lillada01": [40], "unkcls01": [51, 52]},
        other_xref={"badcsk01": "mismatch"},
        players={23: ("LeBron James", 1), 30: ("Jayson Tatum", 2), 40: ("Damian Lillard", 3)},
        team_by_abbr={"PHI": 1, "BOS": 2, "MIL": 3, "POR": 4, "DEN": 5},
        abbr_by_team={1: "PHI", 2: "BOS", 3: "MIL", 4: "POR", 5: "DEN"},
    )
    base.update(kw)
    return DbState(**base)


def _plan(parsed, state, manifest=None):
    return build_plan(parsed, state, manifest or {"sha256": "x"})


def test_identity_buckets(parsed):
    plan = _plan(parsed, _state())
    ident = plan["identity"]
    assert ident["matched"] == 3
    assert ident["not_verified"] == {"badcsk01": "mismatch"}
    assert ident["ambiguous"] == {"unkcls01": [51, 52]}
    assert ident["unmatched"] == []
    plan2 = _plan(parsed, _state(verified_xref={}, other_xref={}))
    assert plan2["identity"]["unmatched"] == ["badcsk01", "jamesle01", "lillada01", "tatumja01", "unkcls01"]


def test_multi_obligation_listed_and_not_compared(parsed):
    state = _state(contracts={40: StoredContract("spotrac", None, "2024-25", [("2026-27", 1, False, False)])})
    plan = _plan(parsed, state)
    multi = plan["multi_obligation_players"]
    assert len(multi) == 1 and multi[0]["bbref_id"] == "lillada01"
    assert [r["team"] for r in multi[0]["rows"]] == ["MIL", "POR"]
    assert plan["stored_contract_comparison"]["not_compared_multi_obligation"] == [
        {"bbref_id": "lillada01", "rows": 2}
    ]
    assert all(p["bbref_id"] != "lillada01" for p in plan["stored_contract_comparison"]["players"])


def test_expired_stored_contract_is_missing_in_stored(parsed):
    stored = StoredContract(
        "spotrac", "2026-01-01T00:00:00+00:00", "2024-25",
        [("2024-25", 48728845, False, False), ("2025-26", 52627153, False, False)],
    )
    plan = _plan(parsed, _state(contracts={23: stored}))
    comp = plan["stored_contract_comparison"]
    lebron = next(p for p in comp["players"] if p["bbref_id"] == "jamesle01")
    assert lebron["coverage"] == "expired"
    assert lebron["seasons"]["2026-27"]["outcome"] == "missing_in_stored"
    assert lebron["seasons"]["2027-28"]["outcome"] == "missing_in_stored"
    assert lebron["source"] == "spotrac"
    assert comp["summary"]["players_without_stored_contract"] == 1


def test_amount_and_option_differences_and_same(parsed):
    stored_amount = StoredContract("spotrac", None, "2026-27", [("2026-27", 5000000, False, False)])
    stored_option = StoredContract(
        "spotrac", None, "2026-27",
        [("2026-27", 34848340, False, False), ("2027-28", 37630747, True, False), ("2028-29", 1, False, False)],
    )
    plan = _plan(parsed, _state(contracts={23: stored_amount, 30: stored_option}))
    players = {p["bbref_id"]: p for p in plan["stored_contract_comparison"]["players"]}
    assert players["jamesle01"]["seasons"]["2026-27"] == {
        "outcome": "amount_differs", "stored": 5000000, "export": 3876529,
        "stored_option": None, "export_option": None,
    }
    assert players["jamesle01"]["coverage"] == "current"
    assert players["tatumja01"]["seasons"]["2026-27"]["outcome"] == "same"
    assert players["tatumja01"]["seasons"]["2027-28"]["outcome"] == "option_differs"
    assert players["tatumja01"]["seasons"]["2028-29"]["outcome"] == "missing_in_export"


def test_team_checks(parsed):
    state = _state(
        players={23: ("LeBron James", 2), 30: ("Jayson Tatum", 2), 40: ("Damian Lillard", None)},
        team_by_abbr={"PHI": 1, "BOS": 2, "MIL": 3, "POR": 4},
    )
    plan = _plan(parsed, state)
    checks = plan["team_checks"]
    assert checks["unknown_team_abbreviations"] == {"DEN": 1, "UTA": 1}
    differs = {(d["bbref_id"], d["obligation_team"]): d for d in checks["team_differs_from_current"]}
    assert differs[("jamesle01", "PHI")]["current_team"] == "BOS"
    assert "tatumja01" not in {k[0] for k in differs}
    assert "lillada01" not in {k[0] for k in differs}
    nct = checks["no_current_team"]
    assert [(d["bbref_id"], d["obligation_team"]) for d in nct] == [("lillada01", "MIL"), ("lillada01", "POR")]
    assert nct[0]["note"] == "player has no current roster team on file"


def test_team_alias_resolution(parsed):
    html = FIXTURE.read_text(encoding="utf-8").replace('/teams/PHI/2027.html">PHI<', '/teams/CHO/2027.html">CHO<')
    aliased = parse_export(html)
    state = _state(
        team_by_abbr={"CHA": 1, "BOS": 2, "MIL": 3, "POR": 4},
        abbr_by_team={1: "CHA", 2: "BOS", 3: "MIL", 4: "POR"},
    )
    checks = _plan(aliased, state)["team_checks"]
    assert "CHO" not in checks["unknown_team_abbreviations"]
    assert all(d["bbref_id"] != "jamesle01" for d in checks["team_differs_from_current"])
    other = _plan(parsed, state)["team_checks"]
    lebron = next(d for d in other["team_differs_from_current"] if d["bbref_id"] == "jamesle01")
    assert lebron["obligation_team_source"] == "PHI" and lebron["obligation_team"] == "PHI"
    assert aliased.rows[0].team_abbr == "CHO"


def test_unmatched_evidence_never_assigns(parsed):
    state = _state(
        verified_xref={"tatumja01": [30]},
        other_xref={},
        name_candidates={
            "lebron james": [NameCandidate(23, "LeBron James", 1, "not_found", None)],
            "damian lillard": [NameCandidate(40, "Damian Lillard", 3, None, None)],
        },
    )
    plan = _plan(parsed, state)
    ident = plan["identity"]
    assert ident["matched"] == 1
    ev = {e["bbref_id"]: e for e in ident["unmatched_evidence"]}
    assert ev["jamesle01"]["category"] == "exact_name_candidates"
    assert ev["jamesle01"]["candidates"][0]["player_id"] == 23
    assert ev["jamesle01"]["candidates"][0]["xref_status"] == "not_found"
    assert ev["jamesle01"]["note"] == "candidate only - not assigned"
    assert ev["badcsk01"]["category"] == "no_player_record" and ev["badcsk01"]["candidates"] == []
    summary = ident["unmatched_evidence_summary"]
    assert summary["exact_name_candidates"] == 2 and summary["no_player_record"] == 2
    assert summary["candidates_without_xref_row"] == 1 and summary["candidates_xref_not_found"] == 1
    assert all(p["bbref_id"] != "jamesle01" for p in plan["stored_contract_comparison"]["players"])


def test_verified_slug_conflict_surfaced_not_assigned(parsed):
    state = _state(
        verified_xref={"tatumja01": [30]},
        other_xref={},
        name_candidates={"lebron james": [NameCandidate(23, "LeBron James", 1, "verified", "jamesle02")]},
    )
    plan = _plan(parsed, state)
    ident = plan["identity"]
    assert ident["matched"] == 1
    ev = {e["bbref_id"]: e for e in ident["unmatched_evidence"]}
    assert ev["jamesle01"]["category"] == "verified_slug_conflict"
    assert ev["jamesle01"]["player_name"] == "LeBron James" and ev["jamesle01"]["team"] == "PHI"
    assert "resolve before any apply" in ev["jamesle01"]["note"]
    assert ident["verified_slug_conflicts"] == [
        {"bbref_id": "jamesle01", "player_name": "LeBron James", "player_id": 23, "stored_verified_slug": "jamesle02"}
    ]
    summary = ident["unmatched_evidence_summary"]
    assert summary["verified_slug_conflict"] == 1 and summary["candidates_verified_slug_conflict"] == 1
    assert summary["candidates_other_status"] == 0
    assert all(p["bbref_id"] != "jamesle01" for p in plan["stored_contract_comparison"]["players"])


def test_coverage_and_no_sums(parsed):
    plan = _plan(parsed, _state())
    cov = plan["coverage"]
    assert cov["rows"] == 6 and cov["distinct_ids"] == 5
    assert cov["option_markers"] == {"player_option": 1, "team_option": 1}
    assert cov["explicit_zero_cells"] == 1
    assert cov["skipped_rows"] == 1
    assert "guaranteed" not in json.dumps(plan).replace("remaining_guaranteed", "").replace("is_guaranteed", "").replace(
        "that is guaranteed", ""
    ).replace("rows_with_remaining_guaranteed", "").replace("remaining salary that is", "")


def test_snapshot_manifest_permissions_and_reuse(tmp_path):
    src = tmp_path / "in.xls"
    src.write_bytes(FIXTURE.read_bytes())
    root = tmp_path / "snaps"
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    target, created = take_snapshot(src, root, now=now)
    assert created
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["export_time"] is None
    assert manifest["export_time_note"].startswith("Unknown")
    assert manifest["received_at_utc"] == now.isoformat()
    assert manifest["original_filename"] == "in.xls"
    assert manifest["bytes"] == src.stat().st_size
    assert target.name == f"sportsref-salaries-{manifest['sha256'][:12]}"
    assert (target / "input.html").read_bytes() == src.read_bytes()
    assert stat.S_IMODE(os.stat(target / "input.html").st_mode) == 0o444
    before = (target / "manifest.json").read_text()
    target2, created2 = take_snapshot(src, root, now=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert target2 == target and not created2
    assert (target / "manifest.json").read_text() == before


def test_existing_snapshot_with_tampered_input_is_refused(tmp_path):
    src = tmp_path / "in.xls"
    src.write_bytes(FIXTURE.read_bytes())
    root = tmp_path / "snaps"
    target, _ = take_snapshot(src, root)
    os.chmod(target / "input.html", 0o644)
    (target / "input.html").write_bytes(b"tampered")
    with pytest.raises(RuntimeError):
        take_snapshot(src, root)
    assert plan_mod.main(["snapshot", "--input", str(src), "--snapshot-root", str(root)]) == 1


def test_plan_refuses_tampered_snapshot(tmp_path):
    src = tmp_path / "in.xls"
    src.write_bytes(FIXTURE.read_bytes())
    target, _ = take_snapshot(src, tmp_path / "snaps")
    os.chmod(target / "input.html", 0o644)
    (target / "input.html").write_bytes(b"tampered")
    assert plan_mod.main(["plan", "--snapshot", str(target)]) == 2


def _variant(old, new):
    html = FIXTURE.read_text(encoding="utf-8")
    assert old in html
    return parse_export(html.replace(old, new, 1))


def _by(details, **kw):
    return [d for d in details if all(d.get(k) == v for k, v in kw.items())]


def test_empty_stored_tables_report_missing_in_stored(parsed):
    plan = _plan(parsed, _state())
    for section in ("player_salaries_comparison", "team_salary_rows_comparison"):
        sec = plan[section]
        assert sec["stored_rows_for_export_seasons"] == 0
        assert sec["summary"]["missing_in_stored"] > 0
        assert _by(sec["details"], bbref_id="jamesle01", season="2026-27")[0]["outcome"] == "missing_in_stored"
        assert _by(sec["details"], bbref_id="jamesle01", season="2027-28")[0]["outcome"] == "missing_in_stored"
        assert sec["not_compared_multi_obligation"] == [{"bbref_id": "lillada01", "rows": 2}]
        assert sec["not_compared_multi_obligation_count"] == 1
        assert not _by(sec["details"], bbref_id="lillada01")


def test_player_salaries_outcomes(parsed):
    state = _state(player_salaries=[(23, "2026-27", 3876529), (23, "2029-30", 5), (30, "2026-27", 1)])
    details = _plan(parsed, state)["player_salaries_comparison"]["details"]
    assert _by(details, bbref_id="jamesle01", season="2026-27")[0]["outcome"] == "same"
    assert _by(details, bbref_id="jamesle01", season="2029-30")[0]["outcome"] == "extra_in_stored"
    assert _by(details, bbref_id="tatumja01", season="2026-27")[0]["outcome"] == "amount_differs"


def test_team_salary_extra_row_and_alias(parsed):
    state = _state(team_salaries=[(23, "2026-27", "PHI", 3876529), (23, "2026-27", "PHI", 99), (30, "2026-27", "BOS", 34848340)])
    details = _plan(parsed, state)["team_salary_rows_comparison"]["details"]
    lebron = _by(details, bbref_id="jamesle01", season="2026-27")
    assert sorted(d["outcome"] for d in lebron) == ["extra_in_stored", "same"]
    assert _by(details, bbref_id="tatumja01", season="2026-27")[0]["outcome"] == "same"


def test_team_salary_alias_both_sides(parsed):
    cho = _variant('/teams/PHI/2027.html">PHI<', '/teams/CHO/2027.html">CHO<')
    state = _state(team_salaries=[(23, "2026-27", "CHA", 3876529)])
    details = _plan(cho, state)["team_salary_rows_comparison"]["details"]
    assert _by(details, bbref_id="jamesle01", season="2026-27")[0]["outcome"] == "same"
    brk = _variant('/teams/PHI/2027.html">PHI<', '/teams/BRK/2027.html">BRK<')
    state = _state(team_salaries=[(23, "2026-27", "BRK", 3876529)])
    details = _plan(brk, state)["team_salary_rows_comparison"]["details"]
    assert _by(details, bbref_id="jamesle01", season="2026-27")[0]["outcome"] == "same"
    assert not _by(details, outcome="extra_in_stored")


def test_uncertain_cells_have_own_outcome():
    tbd = _variant(
        '<td class="right salary-pl" data-stat="y2" csk="4070355">$4,070,355</td>',
        '<td class="right " data-stat="y2">TBD</td>',
    )
    stored = StoredContract("spotrac", None, "2026-27", [("2026-27", 3876529, False, False), ("2027-28", 4070355, False, False)])
    state = _state(contracts={23: stored}, player_salaries=[(23, "2027-28", 4070355)], team_salaries=[(23, "2027-28", "PHI", 4070355)])
    plan = _plan(tbd, state)
    assert plan["coverage"]["uncertain_cells"] == 1
    assert plan["stored_contract_comparison"]["players"][0]["seasons"]["2027-28"]["outcome"] == "uncertain_in_export"
    for section in ("player_salaries_comparison", "team_salary_rows_comparison"):
        details = plan[section]["details"]
        assert _by(details, bbref_id="jamesle01", season="2027-28")[0]["outcome"] == "uncertain_in_export"
        assert not _by(details, outcome="extra_in_stored")
