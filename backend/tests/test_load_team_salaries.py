import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from scoutiq.etl import load_team_salaries as lts
from scoutiq.etl.check_contract_decision_coverage import BbrefPage
from scoutiq.etl.load_team_salaries import (
    DbState,
    apply_plan,
    build_plan,
    main,
    plan_attributions,
    plan_report,
    plan_team_salary_rows,
    read_db_state,
)
from scoutiq.sources.contract_events import SalaryRow, parse_bbref_salary_rows

FIXTURES = Path(__file__).parent / "fixtures" / "contract_decisions"
HTML = (FIXTURES / "bbref_team_salaries.html").read_text(encoding="utf-8")
M = 1_000_000
ABBR_IDS = {"SPR": 101, "RIV": 102}


def team_id_for(abbr):
    return ABBR_IDS.get(abbr)


def _page(slug="fixpl01", rows=None, fetched_on="2026-01-02") -> BbrefPage:
    return BbrefPage(slug, [], rows if rows is not None else parse_bbref_salary_rows(HTML), fetched_on)


def test_parser_extracts_team_abbr_and_keeps_empty_team_rows():
    rows = parse_bbref_salary_rows(HTML)
    assert [(r.season, r.team, r.team_abbr, r.salary) for r in rows] == [
        ("2019-20", "Springfield Foxes", "SPR", 2 * M),
        ("2019-20", "Riverton Owls", "RIV", 900_000),
        ("2022-23", "Riverton Owls", "RIV", 1 * M),
        ("2022-23", "Riverton Owls", "RIV", 500_000),
        ("2022-23", "", None, 300_000),
    ]
    assert SalaryRow("2019-20", "Foxes", 1).team_abbr is None


def test_row_ordinals_for_duplicate_team_rows_and_counts():
    plan = plan_team_salary_rows([_page()], {"fixpl01": 7}, {}, team_id_for)
    keys = [(r["season"], r["team_name"], r["row_ordinal"], r["salary"]) for r in plan.to_insert]
    assert keys == [
        ("2019-20", "Springfield Foxes", 0, 2 * M),
        ("2019-20", "Riverton Owls", 0, 900_000),
        ("2022-23", "Riverton Owls", 0, 1 * M),
        ("2022-23", "Riverton Owls", 1, 500_000),
        ("2022-23", "", 0, 300_000),
    ]
    assert plan.empty_team_name_rows == 1
    assert plan.unmapped_team_rows == 1
    assert plan.to_insert[0]["team_id"] == 101
    assert plan.to_insert[4]["team_id"] is None and plan.to_insert[4]["team_abbr"] is None
    assert plan.to_insert[0]["source_fetched_on"] == date(2026, 1, 2)
    assert plan.to_insert[0]["source_ref"] == "fixpl01"
    assert plan.fetched_on == {"min": "2026-01-02", "max": "2026-01-02"}


def test_unverified_page_skipped_and_counted():
    plan = plan_team_salary_rows([_page(), _page("other01")], {"fixpl01": 7}, {}, team_id_for)
    assert plan.source_pages == 2
    assert plan.source_rows == 10
    assert plan.skipped_unverified_pages == 1
    assert plan.skipped_unverified_rows == 5
    assert len(plan.to_insert) == 5
    assert all(r["player_id"] == 7 for r in plan.to_insert)


def test_insert_unchanged_conflict_and_stored_not_in_source():
    base = (7, "2019-20", "bbref", "Springfield Foxes", 0)
    changed = (7, "2019-20", "bbref", "Riverton Owls", 0)
    orphan = (9, "2018-19", "bbref", "Riverton Owls", 0)
    existing = {base: (2 * M, "SPR", 1), changed: (1 * M, "RIV", 2), orphan: (5, None, 3)}
    plan = plan_team_salary_rows([_page()], {"fixpl01": 7}, existing, team_id_for)
    assert plan.unchanged == [base]
    assert len(plan.to_insert) == 3
    assert plan.stored_not_in_source == [orphan]
    assert plan.conflicts == [
        {
            "player_id": 7,
            "season": "2019-20",
            "team_name": "Riverton Owls",
            "row_ordinal": 0,
            "stored_salary": 1 * M,
            "source_salary": 900_000,
            "stored_id": 2,
            "source_ref": "fixpl01",
        }
    ]
    inserted = {(r["player_id"], r["season"], r["source"], r["team_name"], r["row_ordinal"]) for r in plan.to_insert}
    assert changed not in inserted and base not in inserted


def _events():
    from scoutiq.etl.check_contract_decision_coverage import (
        ProbeInputs,
        attribute_events,
        build_events,
        set_in_window,
    )
    from scoutiq.config import settings

    txn_html = "".join(
        f'<p class="transaction "><strong>{d}</strong>: {t}</p>'
        for d, t in (
            ("July 1, 2019", "Signed a multi-year contract with the Springfield Foxes."),
            ("July 5, 2022", "Signed a multi-year contract with the Riverton Owls."),
        )
    )
    from scoutiq.sources.contract_events import parse_bbref_transactions

    page = BbrefPage("fixpl01", parse_bbref_transactions(txn_html), parse_bbref_salary_rows(HTML), "2026-01-02")
    inputs = ProbeInputs(
        seasons=settings.seasons,
        bbref_pages=[page],
        spotrac_pages=[],
        xref={"fixpl01": 7},
        players={},
        salaries={},
        caps={},
        player_seasons={},
        contracts=[],
        inventory={},
    )
    events, _ = build_events(inputs)
    set_in_window(events, settings.seasons[1:])
    attribute_events(events, {page.slug: page})
    return events


def test_attribution_insert_update_unchanged_orphaned():
    events = _events()
    by_status = {e.attribution.status for e in events}
    assert by_status == {"attributed", "unresolved"}
    fetched = {"fixpl01": "2026-01-02"}

    plan = plan_attributions(events, {}, fetched)
    assert len(plan.to_insert) == 2 and not plan.to_update and not plan.unchanged and not plan.orphaned
    attributed = next(i for i in plan.to_insert if i["status"] == "attributed")
    assert attributed["salary"] == 2 * M
    assert attributed["row_key"] == (7, "2019-20", "bbref", "Springfield Foxes", 0)
    assert attributed["source_fetched_on"] == date(2026, 1, 2)
    unresolved = next(i for i in plan.to_insert if i["status"] == "unresolved")
    assert (unresolved["reason"], unresolved["salary"], unresolved["row_key"]) == (
        "multiple_rows_for_signing_team",
        None,
        None,
    )
    json.dumps(unresolved["evidence"])

    stored = {
        i["event_key"]: {k: i[k] for k in ("status", "reason", "salary", "rule_version", "row_key")}
        for i in plan.to_insert
    }
    again = plan_attributions(events, stored, fetched)
    assert len(again.unchanged) == 2 and not again.to_insert and not again.to_update

    stored[attributed["event_key"]] = {**stored[attributed["event_key"]], "salary": 1}
    stored["7:2000-01-01:standard:gone"] = {
        "status": "unresolved", "reason": "x", "salary": None, "rule_version": "v1", "row_key": None
    }
    changed = plan_attributions(events, stored, fetched)
    assert [i["event_key"] for i in changed.to_update] == [attributed["event_key"]]
    assert changed.orphaned == ["7:2000-01-01:standard:gone"]
    assert len(changed.unchanged) == 1

    stored[attributed["event_key"]] = {**stored[attributed["event_key"]], "salary": 2 * M, "rule_version": "v0"}
    assert [i["event_key"] for i in plan_attributions(events, stored, fetched).to_update] == [
        attributed["event_key"]
    ]


def test_idempotent_replan_against_in_memory_state():
    pages = [_page()]
    events = _events()
    ts = plan_team_salary_rows(pages, {"fixpl01": 7}, {}, team_id_for)
    at = plan_attributions(events, {}, {"fixpl01": "2026-01-02"})
    existing = {
        (r["player_id"], r["season"], r["source"], r["team_name"], r["row_ordinal"]): (r["salary"], r["team_abbr"], n)
        for n, r in enumerate(ts.to_insert, 1)
    }
    stored = {
        i["event_key"]: {k: i[k] for k in ("status", "reason", "salary", "rule_version", "row_key")}
        for i in at.to_insert
    }
    ts2 = plan_team_salary_rows(pages, {"fixpl01": 7}, existing, team_id_for)
    at2 = plan_attributions(events, stored, {"fixpl01": "2026-01-02"})
    assert (len(ts2.to_insert), len(ts2.conflicts), len(ts2.stored_not_in_source)) == (0, 0, 0)
    assert len(ts2.unchanged) == 5
    assert (len(at2.to_insert), len(at2.to_update), len(at2.orphaned)) == (0, 0, 0)
    assert len(at2.unchanged) == 2


def _raw_dir(tmp_path):
    shutil.copy(FIXTURES / "bbref_team_salaries.html", tmp_path / "fixpl01.html")
    return tmp_path


def test_apply_refused_when_tables_missing(tmp_path, capsys):
    raw = _raw_dir(tmp_path)
    reader = lambda: DbState({"fixpl01": 7}, False, {}, {})
    assert main(["--raw-dir", str(raw), "--apply"], db_reader=reader) == 2
    assert "do not exist" in capsys.readouterr().err
    assert main(["--raw-dir", str(raw), "--json"], db_reader=reader) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tables_present"] is False and report["mode"] == "dry_run"
    assert report["team_salary_rows"]["to_insert"] == 5


def test_apply_refused_on_conflict_and_writes_nothing(tmp_path, capsys, monkeypatch):
    raw = _raw_dir(tmp_path)
    key = (7, "2019-20", "bbref", "Springfield Foxes", 0)
    reader = lambda: DbState({"fixpl01": 7}, True, {key: (1, "SPR", 1)}, {})

    def boom():
        raise AssertionError("session must not be opened")

    monkeypatch.setattr("scoutiq.db.get_session", boom)
    assert main(["--raw-dir", str(raw), "--apply"], db_reader=reader) == 2
    assert "conflict" in capsys.readouterr().err
    assert main(["--raw-dir", str(raw), "--json"], db_reader=reader) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["team_salary_rows"]["conflicts"] == 1
    assert report["conflicts"][0]["stored_salary"] == 1


def test_text_report_renders(tmp_path, capsys):
    raw = _raw_dir(tmp_path)
    assert main(["--raw-dir", str(raw)], db_reader=lambda: DbState({"fixpl01": 7}, True, {}, {})) == 0
    out = capsys.readouterr().out
    assert "== mode ==" in out and "to_insert" in out


def test_empty_raw_dir_returns_one(tmp_path):
    assert main(["--raw-dir", str(tmp_path)], db_reader=lambda: DbState({}, True, {}, {})) == 1


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


_DDL = (
    "CREATE TABLE player_xref (bbref_slug TEXT, player_id INTEGER, status TEXT)",
    """CREATE TABLE player_team_salaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL, season TEXT NOT NULL,
        team_name TEXT NOT NULL, team_abbr TEXT, team_id INTEGER, row_ordinal INTEGER NOT NULL,
        salary INTEGER NOT NULL, source TEXT NOT NULL, source_ref TEXT, source_fetched_on DATE,
        loaded_at TIMESTAMP NOT NULL,
        UNIQUE (player_id, season, source, team_name, row_ordinal))""",
    """CREATE TABLE salary_decision_attributions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT NOT NULL UNIQUE, player_id INTEGER NOT NULL,
        signing_date DATE NOT NULL, kind TEXT NOT NULL, team_name TEXT, first_paid_season TEXT NOT NULL,
        status TEXT NOT NULL, reason TEXT, team_salary_id INTEGER, salary INTEGER, rule_version TEXT NOT NULL,
        evidence JSON, source TEXT NOT NULL, source_ref TEXT, source_fetched_on DATE,
        computed_at TIMESTAMP NOT NULL)""",
)


def _sqlite_engine(*, with_tables: bool):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(text(_DDL[0]))
        conn.execute(text("INSERT INTO player_xref VALUES ('fixpl01', 7, 'verified')"))
        if with_tables:
            for stmt in _DDL[1:]:
                conn.execute(text(stmt))
    return engine


def test_end_to_end_apply_on_sqlite_is_idempotent(tmp_path):
    raw = _raw_dir(tmp_path)
    engine = _sqlite_engine(with_tables=True)
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    def reader():
        with engine.connect() as conn:
            return read_db_state(conn)

    plan = build_plan(raw, None, reader)
    assert plan.tables_present
    assert len(plan.team_salaries.to_insert) == 5
    assert len(plan.attributions.to_insert) == 2
    with Session(engine) as session:
        counts = apply_plan(session, plan, now)
        session.commit()
    assert counts["player_team_salaries"] == {"before": 0, "after": 5}
    assert counts["salary_decision_attributions"] == {"before": 0, "after": 2}

    with engine.connect() as conn:
        rows = conn.execute(
            text("select status, reason, salary, team_salary_id from salary_decision_attributions order by event_key")
        ).all()
        assert sorted((r.status, r.reason, r.salary) for r in rows) == [
            ("attributed", None, 2 * M),
            ("unresolved", "multiple_rows_for_signing_team", None),
        ]
        attributed = next(r for r in rows if r.status == "attributed")
        linked = conn.execute(
            text("select team_name, salary from player_team_salaries where id = :i"), {"i": attributed.team_salary_id}
        ).one()
        assert (linked.team_name, linked.salary) == ("Springfield Foxes", 2 * M)
        assert conn.execute(text("select count(*) from player_team_salaries")).scalar() == 5

    replan = build_plan(raw, None, reader)
    assert (len(replan.team_salaries.to_insert), len(replan.team_salaries.conflicts)) == (0, 0)
    assert len(replan.team_salaries.unchanged) == 5
    assert (len(replan.attributions.to_insert), len(replan.attributions.to_update)) == (0, 0)
    assert len(replan.attributions.unchanged) == 2
    with Session(engine) as session:
        before = session.execute(text("select loaded_at from player_team_salaries")).all()
        apply_plan(session, replan, datetime(2027, 1, 1, tzinfo=timezone.utc))
        session.commit()
        assert session.execute(text("select loaded_at from player_team_salaries")).all() == before
    report = plan_report(replan, "dry_run")
    assert report["attributions"]["by_status"] == {"attributed": 1, "unresolved": 1}
    assert report["attributions"]["unresolved_by_reason"]["multiple_rows_for_signing_team"] == 1


def test_sqlite_state_without_tables_reports_not_present(tmp_path):
    engine = _sqlite_engine(with_tables=False)
    with engine.connect() as conn:
        state = read_db_state(conn)
    assert state.tables_present is False
    assert state.team_salaries == {} and state.attributions == {}
    assert state.xref == {"fixpl01": 7}


def test_loader_has_no_network_or_player_salaries_writes():
    src = Path(lts.__file__).read_text(encoding="utf-8")
    for banned in ("import requests", "urllib", "httpx", "socket", "PlayerSalary"):
        assert banned not in src
