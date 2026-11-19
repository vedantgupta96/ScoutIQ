import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from scoutiq.etl import apply_sportsref_salaries as mod
from scoutiq.etl.apply_sportsref_salaries import (
    SOURCE,
    ApplyExtras,
    build_apply_plan,
    main,
)
from scoutiq.etl.plan_sportsref_salaries import DbState, StoredContract, take_snapshot
from scoutiq.models import (
    Base,
    CapConstants,
    Contract,
    ContractYear,
    Player,
    PlayerSalary,
    PlayerTeamSalary,
    PlayerXref,
    Team,
)
from scoutiq.sources.sportsref_salary_export import ObligationRow, ParsedExport, YearCell, parse_export

FIXTURE = Path(__file__).parent / "fixtures" / "sportsref" / "contracts_export.html"
RECEIVED = datetime(2026, 7, 12, 15, 30, tzinfo=timezone.utc)
TABLES = [
    Team.__table__,
    Player.__table__,
    PlayerXref.__table__,
    Contract.__table__,
    ContractYear.__table__,
    PlayerSalary.__table__,
    PlayerTeamSalary.__table__,
    CapConstants.__table__,
]
TEAMS = {1: ("PHI", "Philadelphia 76ers"), 2: ("BOS", "Boston Celtics"), 3: ("MIL", "Milwaukee Bucks"),
         4: ("POR", "Portland Trail Blazers"), 5: ("DEN", "Denver Nuggets")}
OLD = datetime(2025, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=TABLES)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        for tid, (abbr, name) in TEAMS.items():
            s.add(Team(team_id=tid, abbreviation=abbr, name=name))
        s.add_all([Player(player_id=23, full_name="LeBron James", current_team_id=1),
                   Player(player_id=30, full_name="Jayson Tatum", current_team_id=2),
                   Player(player_id=40, full_name="Damian Lillard", current_team_id=3)])
        s.flush()
        s.add_all([PlayerXref(player_id=23, bbref_slug="jamesle01", status="verified"),
                   PlayerXref(player_id=30, bbref_slug="tatumja01", status="verified"),
                   PlayerXref(player_id=40, bbref_slug="lillada01", status="verified")])
        s.add_all([CapConstants(season="2026-27", salary_cap=100_000_000),
                   CapConstants(season="2027-28", salary_cap=None)])
        s.commit()
    factory.engine = engine
    return factory


def snapshot(tmp_path, html=None, name="in"):
    src = tmp_path / f"{name}.html"
    src.write_text(html if html is not None else FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    target, _ = take_snapshot(src, tmp_path / "snaps", now=RECEIVED)
    return target


def confirm_for(snap):
    return json.loads((snap / "manifest.json").read_text())["sha256"][:12]


def run(snap, factory, *extra):
    return main(["apply", "--snapshot", str(snap), *extra], session_factory=factory)


def run_apply(snap, factory):
    return run(snap, factory, "--apply", "--confirm", confirm_for(snap))


def counts(factory):
    with factory() as s:
        return {
            t.__tablename__: s.scalar(select(func.count()).select_from(t))
            for t in (Contract, ContractYear, PlayerTeamSalary, PlayerSalary)
        }


def table_dump(factory):
    with factory() as s:
        out = []
        for t in (Contract, ContractYear, PlayerTeamSalary, PlayerSalary):
            cols = [c.name for c in t.__table__.columns]
            out.append(sorted(tuple(str(getattr(r, c)) for c in cols) for r in s.scalars(select(t))))
        return out


def add_contract(factory, pid, start, years, source="spotrac", scraped_at=OLD):
    with factory() as s:
        c = Contract(player_id=pid, season_start=start, years=len(years), total_value=sum(a for _, a, *_ in years),
                     source=source, scraped_at=scraped_at)
        c.contract_years = [
            ContractYear(season=se, aav=a, is_player_option=po, is_team_option=to, is_guaranteed=not (po or to))
            for se, a, po, to in years
        ]
        s.add(c)
        s.commit()


def contract_rows(factory, pid):
    with factory() as s:
        return list(s.scalars(select(Contract).where(Contract.player_id == pid).order_by(Contract.season_start)))


def test_dry_run_writes_nothing_and_writes_plan_json(tmp_path, factory, capsys):
    snap = snapshot(tmp_path)
    before = table_dump(factory)
    out = tmp_path / "plan.json"
    assert run(snap, factory, "--json", str(out)) == 0
    assert table_dump(factory) == before
    plan = json.loads(out.read_text())
    assert plan["player_salaries"]["written"] == 0
    assert plan["planned_inserts"]["contracts"] == 2
    assert not list(snap.glob("apply-*.json"))
    assert "dry run" in capsys.readouterr().out


@pytest.mark.parametrize("extra", [["--apply"], ["--apply", "--confirm", "deadbeef0000"]])
def test_apply_requires_matching_confirm(tmp_path, factory, extra):
    snap = snapshot(tmp_path)
    before = table_dump(factory)
    assert run(snap, factory, *extra) == 4
    assert table_dump(factory) == before


def test_tampered_snapshot_exit_2_and_format_error_exit_3(tmp_path, factory):
    snap = snapshot(tmp_path)
    (snap / "input.html").chmod(0o644)
    (snap / "input.html").write_text("tampered")
    assert run(snap, factory) == 2
    bad = snapshot(tmp_path, FIXTURE.parent.joinpath("malformed_header.html").read_text(), name="bad")
    assert run(bad, factory) == 3


def test_insert_expired_contract_gets_new_contract_with_schedule(tmp_path, factory):
    add_contract(factory, 23, "2024-25", [("2024-25", 48_000_000, False, False), ("2025-26", 50_000_000, False, False)])
    snap = snapshot(tmp_path)
    assert run_apply(snap, factory) == 0
    new = [c for c in contract_rows(factory, 23) if c.source == SOURCE]
    assert len(new) == 1
    c = new[0]
    assert (c.season_start, c.years, c.total_value, c.team_id) == ("2026-27", 2, 3_876_529 + 4_070_355, 1)
    assert c.scraped_at.replace(tzinfo=timezone.utc) == RECEIVED
    with factory() as s:
        years = list(s.scalars(select(ContractYear).where(ContractYear.contract_id == c.id).order_by(ContractYear.season)))
    assert [(y.season, y.aav, y.is_player_option, y.is_team_option, y.is_guaranteed) for y in years] == [
        ("2026-27", 3_876_529, False, False, None),
        ("2027-28", 4_070_355, True, False, None),
    ]
    with factory() as s:
        assert s.scalar(select(Contract.remaining_guaranteed_usd).where(Contract.id == c.id)) == 3_876_529
    assert float(years[0].cap_pct) == round(3_876_529 / 100_000_000, 4)
    assert years[1].cap_pct is None
    assert len(contract_rows(factory, 23)) == 2


def test_no_stored_contract_inserts_and_team_option_flags(tmp_path, factory):
    snap = snapshot(tmp_path)
    assert run_apply(snap, factory) == 0
    [c] = contract_rows(factory, 30)
    with factory() as s:
        years = list(s.scalars(select(ContractYear).where(ContractYear.contract_id == c.id).order_by(ContractYear.season)))
    assert [(y.is_team_option, y.is_guaranteed) for y in years] == [(False, None), (True, None)]


def test_rerun_is_idempotent_and_unchanged_after_apply(tmp_path, factory):
    snap = snapshot(tmp_path)
    assert run_apply(snap, factory) == 0
    first = counts(factory)
    dump = table_dump(factory)
    assert first["contracts"] == 2 and first["player_team_salaries"] == 9
    plan_path = tmp_path / "p.json"
    assert run(snap, factory, "--json", str(plan_path)) == 0
    plan = json.loads(plan_path.read_text())
    assert plan["contracts"]["counts"]["insert"] == 0 and plan["contracts"]["counts"]["unchanged"] == 2
    assert plan["team_salaries"]["counts"]["insert"] == 0 and plan["team_salaries"]["counts"]["unchanged"] == 9
    assert run_apply(snap, factory) == 0
    assert counts(factory) == first
    assert table_dump(factory) == dump


def test_stored_contract_differs_is_held_and_never_overwritten(tmp_path, factory):
    add_contract(factory, 30, "2026-27", [("2026-27", 1, False, False), ("2027-28", 2, False, False)])
    snap = snapshot(tmp_path)
    plan_path = tmp_path / "p.json"
    run(snap, factory, "--json", str(plan_path))
    plan = json.loads(plan_path.read_text())
    held = {h["bbref_id"]: h for h in plan["contracts"]["held"]}
    assert held["tatumja01"]["reason"] == "stored_contract_differs"
    assert held["tatumja01"]["diff"]["2026-27"]["outcome"] == "amount_differs"
    before = table_dump(factory)
    assert run_apply(snap, factory) == 0
    assert [c.source for c in contract_rows(factory, 30)] == ["spotrac"]
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(ContractYear).join(Contract).where(Contract.player_id == 30)) == 2
        assert s.scalar(select(func.count()).select_from(PlayerTeamSalary).where(PlayerTeamSalary.player_id == 30)) == 2
    assert before[0] != table_dump(factory)[0]


def test_latest_with_same_start_and_no_overlap_would_not_be_latest(tmp_path, factory):
    add_contract(factory, 23, "2026-27", [("2025-26", 1, False, False)])
    snap = snapshot(tmp_path)
    plan_path = tmp_path / "p.json"
    run(snap, factory, "--json", str(plan_path))
    held = {h["bbref_id"]: h for h in json.loads(plan_path.read_text())["contracts"]["held"]}
    assert held["jamesle01"]["reason"] == "would_not_be_latest"


def test_older_contract_overlap_held_even_when_hidden_by_newer_disjoint_contract(tmp_path, factory):
    add_contract(factory, 23, "2025-26", [("2025-26", 1, False, False), ("2026-27", 2, False, False)])
    add_contract(factory, 23, "2028-29", [("2028-29", 3, False, False)])
    snap = snapshot(tmp_path)
    plan_path = tmp_path / "p.json"
    run(snap, factory, "--json", str(plan_path))
    held = {h["bbref_id"]: h for h in json.loads(plan_path.read_text())["contracts"]["held"]}
    assert held["jamesle01"]["reason"] == "older_contract_overlaps"
    assert held["jamesle01"]["overlapping_contracts"] == [
        {"season_start": "2025-26", "source": "spotrac", "seasons": ["2026-27"]}
    ]
    assert run_apply(snap, factory) == 0
    assert [c.source for c in contract_rows(factory, 23)] == ["spotrac", "spotrac"]


def test_newer_disjoint_contract_would_not_be_latest(tmp_path, factory):
    add_contract(factory, 23, "2028-29", [("2028-29", 3, False, False)])
    plan = plan_for(base_state(contracts={23: StoredContract("spotrac", None, "2028-29", [("2028-29", 3, False, False)])}),
                    base_extras(all_contracts={23: [StoredContract("spotrac", None, "2028-29", [("2028-29", 3, False, False)])]}))
    assert held_reasons(plan)["jamesle01"] == "would_not_be_latest"


def custom_plan(cells, guaranteed):
    years = [YearCell(f"{2026 + i}-{27 + i}", amt, opt, False) for i, (amt, opt) in enumerate(cells)]
    row = ObligationRow(0, 1, "jamesle01", "LeBron James", "PHI", years, guaranteed)
    parsed = ParsedExport([y.season for y in years], [row], [])
    return build_apply_plan(parsed, base_state(), base_extras(), MANIFEST, "snap")


def contract_for(plan):
    inserted = [r for r in plan["contracts"]["insert"] if r["bbref_id"] == "jamesle01"]
    return inserted[0] if inserted else None


def test_missing_remaining_guaranteed_stores_unknown_not_held():
    c = contract_for(custom_plan([(5, None), (5, None)], None))
    assert c["guarantee_basis"] == "source_missing"
    assert [y["is_guaranteed"] for y in c["schedule"]] == [None, None]
    assert c["remaining_guaranteed"] is None


def test_equal_firm_years_with_partial_guarantee_is_split_unknown():
    c = contract_for(custom_plan([(5_000_000, None), (5_000_000, None)], 5_000_000))
    assert c["guarantee_basis"] == "split_unknown" and c["remaining_guaranteed"] == 5_000_000
    assert [y["is_guaranteed"] for y in c["schedule"]] == [None, None]


def test_cisse_like_prefix_match_without_options_is_split_unknown():
    c = contract_for(custom_plan([(2_185_116, None), (2_571_895, None)], 2_185_116))
    assert c["guarantee_basis"] == "split_unknown"
    assert [y["is_guaranteed"] for y in c["schedule"]] == [None, None]


def test_guarantee_equals_total_marks_all_guaranteed():
    c = contract_for(custom_plan([(5, None), (7, "team_option")], 12))
    assert c["guarantee_basis"] == "all_guaranteed"
    assert [y["is_guaranteed"] for y in c["schedule"]] == [True, True]
    assert [y["is_team_option"] for y in c["schedule"]] == [False, True]


def test_zero_guarantee_marks_none_guaranteed():
    c = contract_for(custom_plan([(5, None), (7, None)], 0))
    assert c["guarantee_basis"] == "none_guaranteed"
    assert [y["is_guaranteed"] for y in c["schedule"]] == [False, False]


def test_lebron_like_option_year_is_split_unknown_with_options_kept():
    c = contract_for(custom_plan([(3_876_529, None), (4_070_355, "player_option")], 3_876_529))
    assert c["guarantee_basis"] == "split_unknown"
    assert [(y["is_guaranteed"], y["is_player_option"]) for y in c["schedule"]] == [(None, False), (None, True)]
    assert c["remaining_guaranteed"] == 3_876_529


def test_no_guarantee_reasons_hold_contracts():
    plan = plan_for()
    assert not {h["reason"] for h in plan["contracts"]["held"]} & {"guarantee_unknown", "guarantee_unresolved"}
    assert {r["bbref_id"]: r["guarantee_basis"] for r in plan["contracts"]["insert"]} == {
        "jamesle01": "split_unknown", "tatumja01": "split_unknown"}


def test_apply_keeps_existing_is_guaranteed_values_byte_identical(tmp_path, factory):
    add_contract(factory, 23, "2024-25", [("2024-25", 48_000_000, False, False), ("2025-26", 50_000_000, True, False)])
    with factory() as s:
        before = sorted((y.id, y.is_guaranteed) for y in s.scalars(select(ContractYear)))
    snap = snapshot(tmp_path)
    assert run_apply(snap, factory) == 0
    with factory() as s:
        after = {y.id: y.is_guaranteed for y in s.scalars(select(ContractYear))}
    assert all(after[i] == v for i, v in before)
    assert main(["rollback", "--snapshot", str(snap), "--apply", "--confirm", confirm_for(snap)],
                session_factory=factory) == 0
    with factory() as s:
        assert sorted((y.id, y.is_guaranteed) for y in s.scalars(select(ContractYear))) == before


def test_same_received_at_two_snapshots_roll_back_independently(tmp_path, factory):
    snap_a = snapshot(tmp_path)
    html_b = FIXTURE.read_text().replace("tatumja01", "tatumb02")
    snap_b = snapshot(tmp_path, html_b, name="b")
    assert snap_a != snap_b
    with factory() as s:
        s.add(Player(player_id=50, full_name="Other Tatum", current_team_id=2))
        s.flush()
        s.add(PlayerXref(player_id=50, bbref_slug="tatumb02", status="verified"))
        s.commit()
    assert run_apply(snap_a, factory) == 0
    assert run_apply(snap_b, factory) == 0
    with factory() as s:
        refs = {r for r in s.scalars(select(Contract.source_ref).where(Contract.source == SOURCE))}
        assert refs == {snap_a.name, snap_b.name}
    assert main(["rollback", "--snapshot", str(snap_a), "--apply", "--confirm", confirm_for(snap_a)],
                session_factory=factory) == 0
    with factory() as s:
        assert {r for r in s.scalars(select(Contract.source_ref))} == {snap_b.name}
        assert {r for r in s.scalars(select(PlayerTeamSalary.source_ref))} == {snap_b.name}
        assert s.scalar(select(func.count()).select_from(PlayerTeamSalary)) > 0
    assert list(snap_a.glob("rollback-*.json"))
    assert json.loads(next(snap_a.glob("rollback-*.json")).read_text())["status"] == "committed"


def test_missing_source_ref_column_refuses_apply_but_dry_run_works(tmp_path, factory, monkeypatch, capsys):
    snap = snapshot(tmp_path)
    monkeypatch.setattr(mod, "_has_source_ref", lambda session: False)
    before = table_dump(factory)
    assert run(snap, factory) == 0
    assert "0013" in capsys.readouterr().err
    assert run_apply(snap, factory) == 7
    assert main(["rollback", "--snapshot", str(snap), "--apply", "--confirm", confirm_for(snap)],
                session_factory=factory) == 7
    assert table_dump(factory) == before


def test_journal_pending_failure_rolls_back_and_success_ends_committed(tmp_path, factory, monkeypatch):
    snap = snapshot(tmp_path)
    before = table_dump(factory)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(mod, "_write_json", boom)
    assert run_apply(snap, factory) == 6
    assert table_dump(factory) == before
    monkeypatch.undo()
    assert run_apply(snap, factory) == 0
    [path] = list(snap.glob("apply-*.json"))
    assert json.loads(path.read_text())["status"] == "committed"


def _journal(snap, prefix="apply"):
    [path] = list(snap.glob(f"{prefix}-*.json"))
    return json.loads(path.read_text())


def test_lost_commit_acknowledgement_reconciles_as_committed(tmp_path, factory, monkeypatch):
    snap = snapshot(tmp_path)
    real = Session.commit

    def commit_then_raise(self):
        real(self)
        raise RuntimeError("ack lost")

    monkeypatch.setattr(Session, "commit", commit_then_raise)
    assert run_apply(snap, factory) == 0
    monkeypatch.undo()
    journal = _journal(snap)
    assert journal["status"] == "committed_after_reconcile"
    assert journal["reconciliation"]["owned_rows_now"] == {"contracts": 2, "player_team_salaries": 9}
    assert counts(factory)["contracts"] == 2


def test_genuine_commit_failure_reconciles_as_rolled_back_and_raises(tmp_path, factory, monkeypatch):
    snap = snapshot(tmp_path)

    def bad_commit(self):
        self.rollback()
        raise RuntimeError("commit failed")

    monkeypatch.setattr(Session, "commit", bad_commit)
    with pytest.raises(RuntimeError):
        run_apply(snap, factory)
    monkeypatch.undo()
    assert _journal(snap)["status"] == "rolled_back"
    assert counts(factory)["contracts"] == 0


def test_reconcile_failure_leaves_outcome_unknown(tmp_path, factory, monkeypatch):
    snap = snapshot(tmp_path)

    def bad_commit(self):
        self.rollback()
        raise RuntimeError("commit failed")

    def bad_reconcile(*a, **k):
        raise RuntimeError("query failed")

    monkeypatch.setattr(Session, "commit", bad_commit)
    monkeypatch.setattr(mod, "_reconcile_apply", bad_reconcile)
    with pytest.raises(RuntimeError):
        run_apply(snap, factory)
    monkeypatch.undo()
    journal = _journal(snap)
    assert journal["status"] == "outcome_unknown"
    assert "query failed" in journal["reconciliation"]["reconcile_error"]


def test_rollback_lost_acknowledgement_reconciles(tmp_path, factory, monkeypatch):
    snap = snapshot(tmp_path)
    assert run_apply(snap, factory) == 0
    real = Session.commit

    def commit_then_raise(self):
        real(self)
        raise RuntimeError("ack lost")

    monkeypatch.setattr(Session, "commit", commit_then_raise)
    assert main(["rollback", "--snapshot", str(snap), "--apply", "--confirm", confirm_for(snap)],
                session_factory=factory) == 0
    monkeypatch.undo()
    assert _journal(snap, "rollback")["status"] == "committed_after_reconcile"
    assert counts(factory)["contracts"] == 0


def test_final_journal_write_failure_keeps_pending_journal_and_exit_8(tmp_path, factory, monkeypatch, capsys):
    snap = snapshot(tmp_path)
    real_fsync = mod.os.fsync
    calls = []

    def flaky_fsync(fd):
        calls.append(1)
        if len(calls) == 3:
            raise OSError("fsync failed mid-write")
        real_fsync(fd)

    monkeypatch.setattr(mod.os, "fsync", flaky_fsync)
    assert run_apply(snap, factory) == 8
    monkeypatch.undo()
    assert counts(factory)["contracts"] == 2
    assert _journal(snap)["status"] == "pending"
    assert not list(snap.glob("*.tmp"))
    assert "pending journal retained" in capsys.readouterr().err


def test_unknown_marker_cell_holds_contract_and_is_not_written_to_team_salaries(tmp_path, factory):
    html = FIXTURE.read_text().replace('<td class="right " data-stat="y1" csk="3876529">', '<td class="right salary-xx" data-stat="y1" csk="3876529">', 1)
    parsed = parse_export(html)
    assert parsed.rows[0].years[0].uncertain == "unknown_marker:salary-xx"
    snap = snapshot(tmp_path, html, name="xx")
    assert run_apply(snap, factory) == 0
    assert contract_rows(factory, 23) == []
    with factory() as s:
        assert [r.season for r in s.scalars(select(PlayerTeamSalary).where(PlayerTeamSalary.player_id == 23))] == ["2027-28"]
    plan_path = tmp_path / "p.json"
    run(snap, factory, "--json", str(plan_path))
    plan = json.loads(plan_path.read_text())
    assert {h["bbref_id"]: h["reason"] for h in plan["contracts"]["held"]}["jamesle01"] == "uncertain_cells"
    cells = [(c["bbref_id"], c["season"], c["reason"]) for c in plan["team_salaries"]["held_uncertain_cells"]]
    assert ("jamesle01", "2026-27", "unknown_marker:salary-xx") in cells

def test_multi_obligation_writes_team_rows_but_no_contract(tmp_path, factory):
    snap = snapshot(tmp_path)
    assert run_apply(snap, factory) == 0
    assert contract_rows(factory, 40) == []
    with factory() as s:
        rows = list(s.scalars(select(PlayerTeamSalary).where(PlayerTeamSalary.player_id == 40)
                              .order_by(PlayerTeamSalary.season, PlayerTeamSalary.row_ordinal)))
    assert [(r.season, r.team_abbr, r.team_name, r.row_ordinal, r.salary, r.source, r.source_ref) for r in rows] == [
        ("2026-27", "MIL", "Milwaukee Bucks", 2, 22_400_000, SOURCE, snap.name),
        ("2026-27", "POR", "Portland Trail Blazers", 3, 11_000_000, SOURCE, snap.name),
        ("2027-28", "MIL", "Milwaukee Bucks", 2, 22_400_000, SOURCE, snap.name),
        ("2027-28", "POR", "Portland Trail Blazers", 3, 0, SOURCE, snap.name),
        ("2028-29", "MIL", "Milwaukee Bucks", 2, 22_400_000, SOURCE, snap.name),
    ]
    assert rows[0].team_id == 3 and rows[0].source_fetched_on.isoformat() == "2026-07-12"


def parsed_fixture():
    return parse_export(FIXTURE.read_text(encoding="utf-8"))


def base_state(**kw):
    base = dict(
        verified_xref={"jamesle01": [23], "tatumja01": [30], "lillada01": [40]},
        players={23: ("LeBron James", 1), 30: ("Jayson Tatum", 2), 40: ("Damian Lillard", 3)},
        team_by_abbr={v[0]: k for k, v in TEAMS.items()},
        abbr_by_team={k: v[0] for k, v in TEAMS.items()},
    )
    base.update(kw)
    return DbState(**base)


def base_extras(**kw):
    base = dict(team_name_by_id={k: v[1] for k, v in TEAMS.items()}, cap_by_season={})
    base.update(kw)
    return ApplyExtras(**base)


MANIFEST = {"sha256": "a" * 64, "received_at_utc": RECEIVED.isoformat()}


def plan_for(state=None, extras=None):
    return build_apply_plan(parsed_fixture(), state or base_state(), extras or base_extras(), MANIFEST, "snap")


def held_reasons(plan):
    return {h["bbref_id"]: h["reason"] for h in plan["contracts"]["held"]}


def test_team_differs_held_and_no_current_team_allowed():
    plan = plan_for(base_state(players={23: ("LeBron James", 5), 30: ("Jayson Tatum", None), 40: ("Damian Lillard", 3)}))
    assert held_reasons(plan)["jamesle01"] == "team_differs_from_current"
    assert [r["bbref_id"] for r in plan["contracts"]["insert"]] == ["tatumja01"]
    assert {r["bbref_id"] for r in plan["team_salaries"]["insert"]} >= {"jamesle01", "tatumja01"}


def test_unmatched_not_verified_ambiguous_never_written():
    state = base_state(
        verified_xref={"jamesle01": [23], "lillada01": [40, 41], "badcsk01": []},
        other_xref={"tatumja01": "mismatch"},
    )
    plan = plan_for(state)
    reasons = held_reasons(plan)
    assert reasons["tatumja01"] == "not_verified"
    assert reasons["lillada01"] == "ambiguous_identity"
    assert reasons["badcsk01"] == "not_matched"
    written = {r["bbref_id"] for r in plan["team_salaries"]["insert"]}
    assert written == {"jamesle01"}
    assert {h["reason"] for h in plan["team_salaries"]["held_rows"]} >= {"not_verified", "ambiguous_identity", "not_matched"}


def test_unknown_team_held_everywhere():
    plan = plan_for(base_state(team_by_abbr={"PHI": 1, "BOS": 2, "MIL": 3, "POR": 4}))
    assert held_reasons(plan)["badcsk01"] == "not_matched"
    state = base_state(
        verified_xref={"jamesle01": [23], "tatumja01": [30], "lillada01": [40], "unkcls01": [60]},
        players={23: ("LeBron James", 1), 30: ("Jayson Tatum", 2), 40: ("Damian Lillard", 3), 60: ("X", None)},
    )
    plan = plan_for(state)
    assert held_reasons(plan)["unkcls01"] == "unknown_team"
    assert any(h["reason"] == "unknown_team" for h in plan["team_salaries"]["held_rows"])


def test_phx_style_alias_resolves():
    html = FIXTURE.read_text().replace('/teams/BOS/2027.html">BOS', '/teams/PHO/2027.html">PHO')
    parsed = parse_export(html)
    state = base_state(team_by_abbr={"PHX": 2, "PHI": 1, "MIL": 3, "POR": 4}, abbr_by_team={2: "PHX", 1: "PHI", 3: "MIL", 4: "POR"},
                       players={23: ("L", 1), 30: ("T", 2), 40: ("D", 3)})
    extras = base_extras(team_name_by_id={1: "Philadelphia 76ers", 2: "Phoenix Suns", 3: "Milwaukee Bucks", 4: "Portland Trail Blazers"})
    plan = build_apply_plan(parsed, state, extras, MANIFEST, "snap")
    tatum = [r for r in plan["team_salaries"]["insert"] if r["bbref_id"] == "tatumja01"]
    assert {(r["team_abbr"], r["team_name"]) for r in tatum} == {("PHX", "Phoenix Suns")}


def test_uncertain_cell_holds_contract_and_skips_that_cell(tmp_path, factory):
    html = FIXTURE.read_text().replace('csk="3876529">$3,876,529</td>', 'csk="abc">$3,876,529</td>', 1)
    snap = snapshot(tmp_path, html, name="unc")
    assert run_apply(snap, factory) == 0
    assert contract_rows(factory, 23) == []
    with factory() as s:
        seasons = [r.season for r in s.scalars(select(PlayerTeamSalary).where(PlayerTeamSalary.player_id == 23))]
    assert seasons == ["2027-28"]
    plan_path = tmp_path / "p.json"
    run(snap, factory, "--json", str(plan_path))
    plan = json.loads(plan_path.read_text())
    assert {h["bbref_id"]: h["reason"] for h in plan["contracts"]["held"]}["jamesle01"] == "uncertain_cells"
    assert [(c["bbref_id"], c["season"]) for c in plan["team_salaries"]["held_uncertain_cells"]] == [("jamesle01", "2026-27")]


def test_team_salary_conflict_refuses_and_writes_nothing(tmp_path, factory, capsys):
    snap = snapshot(tmp_path)
    with factory() as s:
        s.add(PlayerTeamSalary(player_id=30, season="2026-27", team_name="Boston Celtics", team_abbr="BOS", team_id=2,
                               row_ordinal=1, salary=5, source=SOURCE, source_ref="older", loaded_at=OLD))
        s.commit()
    before = table_dump(factory)
    assert run_apply(snap, factory) == 5
    assert table_dump(factory) == before
    assert not list(snap.glob("apply-*.json"))
    assert "conflict" in capsys.readouterr().err
    assert run(snap, factory) == 0


def test_count_mismatch_rolls_back(tmp_path, factory, monkeypatch):
    snap = snapshot(tmp_path)
    before = table_dump(factory)
    real = mod._count_tables
    calls = []

    def fake(session):
        out = real(session)
        calls.append(1)
        if len(calls) == 2:
            out["contracts"] += 1
        return out

    monkeypatch.setattr(mod, "_count_tables", fake)
    assert run_apply(snap, factory) == 6
    assert table_dump(factory) == before
    assert not list(snap.glob("apply-*.json"))


def test_journal_written_on_apply_only(tmp_path, factory):
    add_contract(factory, 23, "2024-25", [("2024-25", 48_000_000, False, False)])
    snap = snapshot(tmp_path)
    run(snap, factory)
    assert not list(snap.glob("apply-*.json"))
    assert run_apply(snap, factory) == 0
    [path] = list(snap.glob("apply-*.json"))
    journal = json.loads(path.read_text())
    assert journal["sha256"] == json.loads((snap / "manifest.json").read_text())["sha256"]
    assert journal["confirm"] == confirm_for(snap)
    assert len(journal["inserted_contract_ids"]) == 2 and len(journal["inserted_team_salary_ids"]) == 9
    assert journal["table_counts"]["before"]["contracts"] == 1 and journal["table_counts"]["after"]["contracts"] == 3
    lebron = next(r for r in journal["before_records"] if r["player_id"] == 23)
    assert lebron["latest_contract"]["source"] == "spotrac"
    assert lebron["latest_contract"]["season_start"] == "2024-25"
    assert journal["plan_summary"]["planned_inserts"]["contracts"] == 2


def test_historical_rows_unchanged_after_apply(tmp_path, factory):
    add_contract(factory, 23, "2024-25", [("2024-25", 48_000_000, False, False)])
    add_contract(factory, 40, "2023-24", [("2023-24", 45_000_000, False, False)])
    with factory() as s:
        s.add(PlayerSalary(player_id=23, season="2025-26", salary=50_000_000, source="bbref"))
        s.add(PlayerTeamSalary(player_id=23, season="2025-26", team_name="Los Angeles Lakers", team_abbr="LAL",
                               team_id=None, row_ordinal=0, salary=50_000_000, source="bbref", source_ref="jamesle01",
                               loaded_at=OLD))
        s.commit()
    snap = snapshot(tmp_path)
    before = table_dump(factory)
    assert run_apply(snap, factory) == 0
    after = table_dump(factory)
    for i in (0, 1, 2):
        assert set(before[i]) <= set(after[i])
    assert after[3] == before[3]
    kept = [r for r in after[2] if "bbref" in r]
    assert kept == [r for r in before[2] if "bbref" in r]


def test_rollback_dry_run_apply_and_reapply(tmp_path, factory, capsys):
    add_contract(factory, 23, "2024-25", [("2024-25", 48_000_000, False, False)])
    add_contract(factory, 30, "2020-21", [("2020-21", 1, False, False)], source="other", scraped_at=RECEIVED)
    with factory() as s:
        s.add(PlayerTeamSalary(player_id=30, season="2026-27", team_name="Boston Celtics", team_abbr="BOS", team_id=2,
                               row_ordinal=0, salary=7, source="bbref", source_ref=None, loaded_at=OLD))
        s.add(PlayerTeamSalary(player_id=30, season="2026-27", team_name="Boston Celtics", team_abbr="BOS", team_id=2,
                               row_ordinal=0, salary=8, source=SOURCE, source_ref="sportsref-salaries-other", loaded_at=OLD))
        s.commit()
    snap = snapshot(tmp_path)
    assert run_apply(snap, factory) == 0
    applied = table_dump(factory)
    capsys.readouterr()

    assert main(["rollback", "--snapshot", str(snap)], session_factory=factory) == 0
    out = capsys.readouterr().out
    assert "contracts 2, contract_years 4, player_team_salaries 9" in out
    assert "player 23" in out and "player 40" in out
    assert table_dump(factory) == applied

    assert main(["rollback", "--snapshot", str(snap), "--apply"], session_factory=factory) == 4
    assert table_dump(factory) == applied
    assert main(["rollback", "--snapshot", str(snap), "--apply", "--confirm", confirm_for(snap)], session_factory=factory) == 0
    c = counts(factory)
    assert c["contracts"] == 2 and c["contract_years"] == 2 and c["player_team_salaries"] == 2
    with factory() as s:
        assert {(r.source, r.salary) for r in s.scalars(select(PlayerTeamSalary))} == {("bbref", 7), (SOURCE, 8)}
        assert {c.source for c in s.scalars(select(Contract))} == {"spotrac", "other"}

    assert run_apply(snap, factory) == 0
    again = table_dump(factory)
    assert [len(x) for x in again] == [len(x) for x in applied]
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(PlayerTeamSalary).where(PlayerTeamSalary.source_ref == snap.name)) == 9


def test_two_runs_with_identical_now_get_distinct_journals(tmp_path, factory, monkeypatch):
    frozen = datetime(2026, 8, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(mod, "datetime", FrozenDatetime)
    snap = snapshot(tmp_path)
    assert run_apply(snap, factory) == 0
    first = sorted(snap.glob("apply-*.json"))
    assert len(first) == 1
    first_text = first[0].read_text()
    assert run_apply(snap, factory) == 0
    both = sorted(snap.glob("apply-*.json"))
    assert len(both) == 2 and first[0] in both
    assert first[0].read_text() == first_text
    assert len(json.loads(first_text)["inserted_contract_ids"]) == 2
    assert json.loads([p for p in both if p != first[0]][0].read_text())["inserted_contract_ids"] == []
    assert all(".123456Z-" in p.name for p in both)


def test_reserve_journal_refuses_to_replace_existing(tmp_path):
    path = tmp_path / "apply-x.json"
    path.write_text("{}")
    with pytest.raises(FileExistsError):
        mod._reserve_journal(path)
    assert path.read_text() == "{}"
