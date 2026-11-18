import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from scoutiq.etl import load_team_salaries as lts
from scoutiq.etl.contract_decision_events import (
    BbrefPage,
    attribute_events,
    build_events,
    set_in_window,
)
from scoutiq.etl.load_team_salaries import (
    DbState,
    apply_plan,
    attributed_row_keys,
    build_plan,
    main,
    plan_attributions,
    plan_report,
    plan_team_salary_rows,
    read_db_state,
    reconcile_season_evidence,
)
from scoutiq.sources.contract_events import SalaryRow, parse_bbref_salary_rows, parse_bbref_transactions

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


def _txn_page(txns, rows, slug="fixpl01"):
    html = "".join(
        f'<p class="transaction "><strong>{d}</strong>: {t}</p>' for d, t in txns
    )
    return BbrefPage(slug, parse_bbref_transactions(html), rows, "2026-01-02")


def _fixture_page():
    return _txn_page(
        (
            ("July 1, 2019", "Signed a multi-year contract with the Springfield Foxes."),
            ("July 5, 2022", "Signed a multi-year contract with the Riverton Owls."),
        ),
        parse_bbref_salary_rows(HTML),
    )


def _evidence_events(pages, stored=None, xref=None):
    from scoutiq.config import settings

    xref = xref or {"fixpl01": 7}
    stored = stored or {}
    ts = plan_team_salary_rows(pages, xref, stored, team_id_for)
    evidence = reconcile_season_evidence(pages, xref, stored, ts.stored_not_in_source)
    events, _ = build_events(pages, xref)
    set_in_window(events, settings.seasons[1:])
    attribute_events(
        events,
        {p.slug: p for p in pages},
        lambda ev: [r for _k, r in evidence.get((ev.player_id, ev.first_paid_season), [])],
    )
    return events, evidence


def _events():
    events, evidence = _evidence_events([_fixture_page()])
    return events, attributed_row_keys(events, evidence)


def test_attribution_insert_update_unchanged_orphaned():
    events, row_keys = _events()
    by_status = {e.attribution.status for e in events}
    assert by_status == {"attributed", "unresolved"}
    fetched = {"fixpl01": "2026-01-02"}

    plan = plan_attributions(events, {}, fetched, row_keys)
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
        i["event_key"]: {k: i[k] for k in ("status", "reason", "salary", "rule_version", "row_key", "evidence")}
        for i in plan.to_insert
    }
    again = plan_attributions(events, stored, fetched, row_keys)
    assert len(again.unchanged) == 2 and not again.to_insert and not again.to_update

    stored[attributed["event_key"]] = {**stored[attributed["event_key"]], "salary": 1}
    stored["7:2000-01-01:standard:gone"] = {
        "status": "unresolved", "reason": "x", "salary": None, "rule_version": "v1", "row_key": None
    }
    changed = plan_attributions(events, stored, fetched, row_keys)
    assert [i["event_key"] for i in changed.to_update] == [attributed["event_key"]]
    assert changed.orphaned == ["7:2000-01-01:standard:gone"]
    assert len(changed.unchanged) == 1

    stored[attributed["event_key"]] = {**stored[attributed["event_key"]], "salary": 2 * M, "rule_version": "v0"}
    assert [i["event_key"] for i in plan_attributions(events, stored, fetched, row_keys).to_update] == [
        attributed["event_key"]
    ]


SIGN_TXN = (("July 1, 2019", "Signed a multi-year contract with the Springfield Foxes."),)
FOX0 = (7, "2019-20", "bbref", "Springfield Foxes", 0)
FOX1 = (7, "2019-20", "bbref", "Springfield Foxes", 1)
OWL0 = (7, "2019-20", "bbref", "Riverton Owls", 0)
FOX_ROW = SalaryRow("2019-20", "Springfield Foxes", 2 * M, "SPR")


def _plan_with(rows, stored, attributions=None):
    page = _txn_page(SIGN_TXN, rows)
    return build_plan(
        Path("."),
        None,
        lambda: DbState({"fixpl01": 7}, True, stored, attributions or {}),
        pages=[page],
    )


def test_stored_second_row_for_signing_team_blocks_attribution():
    stored = {FOX0: (2 * M, "SPR", 1), FOX1: (500_000, "SPR", 2)}
    existing = {
        "7:2019-07-01:standard:springfield-foxes": {
            "status": "attributed",
            "reason": None,
            "salary": 2 * M,
            "rule_version": "v1",
            "row_key": FOX0,
        }
    }
    plan = _plan_with([FOX_ROW], stored, existing)
    assert plan.attributions_by_status == {"attributed": 0, "unresolved": 1}
    assert plan.unresolved_by_reason["multiple_rows_for_signing_team"] == 1
    assert plan.events_with_stored_only_evidence == 1
    assert [(i["status"], i["reason"], i["row_key"]) for i in plan.attributions.to_update] == [
        ("unresolved", "multiple_rows_for_signing_team", None)
    ]
    assert plan.team_salaries.stored_not_in_source == [FOX1]


def test_stored_only_row_for_signing_team_attributes_when_cache_lost_season():
    plan = _plan_with([], {FOX0: (2 * M, "SPR", 55)})
    assert plan.attributions_by_status == {"attributed": 1, "unresolved": 0}
    item = plan.attributions.to_insert[0]
    assert (item["row_key"], item["salary"]) == (FOX0, 2 * M)
    assert plan.events_with_stored_only_evidence == 1


def test_stored_only_row_for_other_team_does_not_block_attribution():
    plan = _plan_with([FOX_ROW], {FOX0: (2 * M, "SPR", 1), OWL0: (900_000, "RIV", 2)})
    assert plan.attributions_by_status == {"attributed": 1, "unresolved": 0}
    assert plan.attributions.to_insert[0]["row_key"] == FOX0
    assert plan.events_with_stored_only_evidence == 1
    assert plan_report(plan, "dry_run")["attributions"]["events_with_stored_only_evidence"] == 1


def test_idempotent_replan_with_stored_only_rows():
    stored = {FOX0: (2 * M, "SPR", 1), OWL0: (900_000, "RIV", 2)}
    first = _plan_with([FOX_ROW], stored)
    recorded = {
        i["event_key"]: {k: i[k] for k in ("status", "reason", "salary", "rule_version", "row_key", "evidence")}
        for i in first.attributions.to_insert
    }
    again = _plan_with([FOX_ROW], stored, recorded)
    assert (len(again.attributions.to_insert), len(again.attributions.to_update)) == (0, 0)
    assert len(again.attributions.unchanged) == 1
    assert (len(again.team_salaries.to_insert), len(again.team_salaries.conflicts)) == (0, 0)


def test_idempotent_replan_against_in_memory_state():
    pages = [_page()]
    events, row_keys = _events()
    ts = plan_team_salary_rows(pages, {"fixpl01": 7}, {}, team_id_for)
    at = plan_attributions(events, {}, {"fixpl01": "2026-01-02"}, row_keys)
    existing = {
        (r["player_id"], r["season"], r["source"], r["team_name"], r["row_ordinal"]): (r["salary"], r["team_abbr"], n)
        for n, r in enumerate(ts.to_insert, 1)
    }
    stored = {
        i["event_key"]: {k: i[k] for k in ("status", "reason", "salary", "rule_version", "row_key", "evidence")}
        for i in at.to_insert
    }
    ts2 = plan_team_salary_rows(pages, {"fixpl01": 7}, existing, team_id_for)
    at2 = plan_attributions(events, stored, {"fixpl01": "2026-01-02"}, row_keys)
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
    assert replan.attributions.orphaned == []
    again = build_plan(raw, None, reader)
    assert (again.attributions.to_insert, again.attributions.to_update) == ([], [])
    with Session(engine) as session:
        before = session.execute(text("select loaded_at from player_team_salaries")).all()
        apply_plan(session, replan, datetime(2027, 1, 1, tzinfo=timezone.utc))
        session.commit()
        assert session.execute(text("select loaded_at from player_team_salaries")).all() == before
    report = plan_report(replan, "dry_run")
    assert report["attributions"]["by_status"] == {"attributed": 1, "unresolved": 1}
    assert report["attributions"]["unresolved_by_reason"]["multiple_rows_for_signing_team"] == 1


def test_apply_links_attribution_to_stored_only_row_on_sqlite():
    engine = _sqlite_engine(with_tables=True)
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO player_team_salaries (id, player_id, season, team_name, team_abbr, row_ordinal, "
                "salary, source, loaded_at) VALUES (55, 7, '2019-20', 'Springfield Foxes', 'SPR', 0, :s, "
                "'bbref', :t)"
            ),
            {"s": 2 * M, "t": now.replace(tzinfo=None)},
        )

    def reader():
        with engine.connect() as conn:
            return read_db_state(conn)

    page = _txn_page(SIGN_TXN, [])
    plan = build_plan(Path("."), None, reader, pages=[page])
    assert plan.team_salaries.to_insert == [] and plan.team_salaries.stored_not_in_source == [FOX0]
    assert len(plan.attributions.to_insert) == 1
    with Session(engine) as session:
        apply_plan(session, plan, now)
        session.commit()
    with engine.connect() as conn:
        row = conn.execute(
            text("select status, team_salary_id, salary from salary_decision_attributions")
        ).one()
    assert (row.status, row.team_salary_id, row.salary) == ("attributed", 55, 2 * M)
    replan = build_plan(Path("."), None, reader, pages=[page])
    assert len(replan.attributions.unchanged) == 1
    assert (len(replan.attributions.to_insert), len(replan.attributions.to_update)) == (0, 0)


def test_sqlite_state_without_tables_reports_not_present(tmp_path):
    engine = _sqlite_engine(with_tables=False)
    with engine.connect() as conn:
        state = read_db_state(conn)
    assert state.tables_present is False
    assert state.team_salaries == {} and state.attributions == {}
    assert state.xref == {"fixpl01": 7}


def test_loader_has_no_network_or_player_salaries_writes():
    src = Path(lts.__file__).read_text(encoding="utf-8")
    for banned in ("import requests", "urllib", "httpx", "socket", "PlayerSalary", "check_contract_decision_coverage"):
        assert banned not in src


FOX_KEY = "7:2019-07-01:standard:springfield-foxes"


def _stored_record(event_key, status, reason, evidence, *, team="Springfield Foxes", season="2019-20"):
    return {
        "status": status,
        "reason": reason,
        "salary": None,
        "rule_version": "v1",
        "row_key": None,
        "player_id": 7,
        "first_paid_season": season,
        "team_name": team,
        "evidence": evidence,
    }


def _zero_evidence(**over):
    return {
        "team_signings_in_season": 1,
        "prior_terminations_by_team": 0,
        "prior_service_with_team": 0,
        "prior_releases_team_unknown": 0,
        **over,
    }


def test_stored_signing_evidence_survives_cache_refresh_on_sqlite():
    engine = _sqlite_engine(with_tables=True)
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    waiver = ("July 2, 2019", "Waived by the Springfield Foxes.")
    early = ("July 5, 2019", "Signed a multi-year contract with the Springfield Foxes.")
    late = ("July 20, 2019", "Signed a multi-year contract with the Springfield Foxes.")

    def reader():
        with engine.connect() as conn:
            return read_db_state(conn)

    v1 = _txn_page((waiver, early, late), [FOX_ROW])
    plan1 = build_plan(Path("."), None, reader, pages=[v1])
    assert plan1.attributions_by_status == {"attributed": 0, "unresolved": 2}
    assert plan1.unresolved_by_reason["multiple_signings_with_team"] == 2
    with Session(engine) as session:
        apply_plan(session, plan1, now)
        session.commit()

    v2 = _txn_page((late,), [FOX_ROW])
    plan2 = build_plan(Path("."), None, reader, pages=[v2])
    assert plan2.attributions_by_status == {"attributed": 0, "unresolved": 1}
    assert plan2.unresolved_by_reason["multiple_signings_with_team"] == 1
    assert plan2.promotions == 0
    assert plan2.attributions.to_update == [] and plan2.attributions.to_insert == []
    assert plan2.attributions.unchanged == ["7:2019-07-20:standard:springfield-foxes"]
    assert plan2.attributions.orphaned == ["7:2019-07-05:standard:springfield-foxes"]
    assert plan2.events_with_stored_signing_evidence == 1
    report = plan_report(plan2, "dry_run")["attributions"]
    assert (report["events_with_stored_signing_evidence"], report["promotions"]) == (1, 0)

    query = text("select event_key, status, reason, salary from salary_decision_attributions order by event_key")
    with engine.connect() as conn:
        before = conn.execute(query).all()
    with Session(engine) as session:
        apply_plan(session, plan2, datetime(2027, 1, 1, tzinfo=timezone.utc))
        session.commit()
    with engine.connect() as conn:
        after = conn.execute(query).all()
    assert after == before


def test_stored_termination_evidence_blocks_after_waiver_dropped_from_cache():
    stored = {
        FOX_KEY: _stored_record(
            FOX_KEY, "unresolved", "earlier_termination_by_signing_team", _zero_evidence(prior_terminations_by_team=1)
        )
    }
    plan = _plan_with([FOX_ROW], {FOX0: (2 * M, "SPR", 1)}, stored)
    assert plan.attributions_by_status == {"attributed": 0, "unresolved": 1}
    assert plan.unresolved_by_reason["earlier_termination_by_signing_team"] == 1
    assert plan.events_with_stored_signing_evidence == 1
    assert [i["event_key"] for i in plan.attributions.to_update] == [FOX_KEY]
    assert plan.attributions.to_update[0]["evidence"]["prior_terminations_by_team"] == 1
    assert plan.promotions == 0


def test_empty_db_leaves_attribution_unadjusted():
    plan = _plan_with([FOX_ROW], {})
    assert plan.attributions_by_status == {"attributed": 1, "unresolved": 0}
    assert (plan.events_with_stored_signing_evidence, plan.promotions) == (0, 0)
    assert len(plan.attributions.to_insert) == 1


@pytest.mark.parametrize(
    "orphan_key,team,season",
    [
        ("7:2019-06-01:standard:riverton-owls", "Riverton Owls", "2019-20"),
        ("7:2018-07-01:standard:springfield-foxes", "Springfield Foxes", "2018-19"),
    ],
)
def test_orphan_for_other_team_or_season_does_not_block(orphan_key, team, season):
    stored = {
        orphan_key: _stored_record(
            orphan_key, "unresolved", "no_row_for_signing_team", _zero_evidence(), team=team, season=season
        )
    }
    plan = _plan_with([FOX_ROW], {FOX0: (2 * M, "SPR", 1)}, stored)
    assert plan.attributions_by_status == {"attributed": 1, "unresolved": 0}
    assert plan.attributions.orphaned == [orphan_key]
    assert plan.events_with_stored_signing_evidence == 0


def test_promotions_counts_unresolved_to_attributed_updates():
    stored = {FOX_KEY: _stored_record(FOX_KEY, "unresolved", "no_salary_rows_for_season", _zero_evidence())}
    plan = _plan_with([FOX_ROW], {FOX0: (2 * M, "SPR", 1)}, stored)
    assert plan.attributions_by_status == {"attributed": 1, "unresolved": 0}
    assert [i["event_key"] for i in plan.attributions.to_update] == [FOX_KEY]
    assert plan.promotions == 1
    assert plan.events_with_stored_signing_evidence == 0
    assert plan_report(plan, "dry_run")["attributions"]["promotions"] == 1


def _reader_for(engine):
    def reader():
        with engine.connect() as conn:
            return read_db_state(conn)

    return reader


def _apply(engine, plan, now=datetime(2026, 7, 1, tzinfo=timezone.utc)):
    with Session(engine) as session:
        apply_plan(session, plan, now)
        session.commit()


def _stored_row(engine):
    with engine.connect() as conn:
        row = conn.execute(
            text("select status, reason, salary, evidence from salary_decision_attributions")
        ).one()
    evidence = row.evidence if isinstance(row.evidence, dict) else json.loads(row.evidence)
    return row.status, row.reason, row.salary, evidence


def test_new_evidence_is_saved_when_status_and_reason_are_unchanged():
    engine = _sqlite_engine(with_tables=True)
    reader = _reader_for(engine)
    waiver = ("July 2, 2019", "Waived by the Springfield Foxes.")
    sign = ("July 5, 2019", "Signed a multi-year contract with the Springfield Foxes.")
    key = "7:2019-07-05:standard:springfield-foxes"

    plan1 = build_plan(Path("."), None, reader, pages=[_txn_page((sign,), [])])
    assert plan1.unresolved_by_reason["no_salary_rows_for_season"] == 1
    _apply(engine, plan1)
    status, reason, _salary, evidence = _stored_row(engine)
    assert (status, reason, evidence["prior_terminations_by_team"]) == (
        "unresolved",
        "no_salary_rows_for_season",
        0,
    )

    plan2 = build_plan(Path("."), None, reader, pages=[_txn_page((waiver, sign), [])])
    assert plan2.unresolved_by_reason["no_salary_rows_for_season"] == 1
    assert [i["event_key"] for i in plan2.attributions.to_update] == [key]
    assert plan2.attributions.unchanged == []
    _apply(engine, plan2)
    status, reason, _salary, evidence = _stored_row(engine)
    assert (status, reason, evidence["prior_terminations_by_team"]) == (
        "unresolved",
        "no_salary_rows_for_season",
        1,
    )

    plan3 = build_plan(Path("."), None, reader, pages=[_txn_page((sign,), [FOX_ROW])])
    assert plan3.attributions_by_status == {"attributed": 0, "unresolved": 1}
    assert plan3.unresolved_by_reason["earlier_termination_by_signing_team"] == 1
    assert plan3.promotions == 0
    _apply(engine, plan3)
    status, reason, salary, _evidence = _stored_row(engine)
    assert (status, reason, salary) == ("unresolved", "earlier_termination_by_signing_team", None)


def test_combined_entry_stays_combined_after_wording_loses_detail():
    engine = _sqlite_engine(with_tables=True)
    reader = _reader_for(engine)
    combined = (
        "July 1, 2019",
        "Signed two 10-day contracts with the Springfield Foxes, then signed a contract for the rest of the season.",
    )

    plain = ("July 1, 2019", "Signed a contract for the rest of the season with the Springfield Foxes.")

    plan1 = build_plan(Path("."), None, reader, pages=[_txn_page((combined,), [FOX_ROW])])
    assert plan1.attributions_by_status == {"attributed": 0, "unresolved": 1}
    assert plan1.unresolved_by_reason["entry_combines_forms"] == 1
    _apply(engine, plan1)
    status, reason, _salary, evidence = _stored_row(engine)
    assert (status, reason, evidence["entry_combines_forms"]) == ("unresolved", "entry_combines_forms", True)

    plan2 = build_plan(Path("."), None, reader, pages=[_txn_page((plain,), [FOX_ROW])])
    assert plan2.attributions_by_status == {"attributed": 0, "unresolved": 1}
    assert plan2.unresolved_by_reason["entry_combines_forms"] == 1
    assert plan2.promotions == 0
    assert plan2.events_with_stored_signing_evidence == 1


@pytest.mark.parametrize(
    "reason",
    [
        "multiple_signings_with_team",
        "entry_combines_forms",
        "earlier_termination_by_signing_team",
        "earlier_service_with_signing_team",
        "earlier_release_team_unknown",
    ],
)
def test_stored_reason_floors_keep_event_unresolved_without_evidence(reason):
    stored = {FOX_KEY: _stored_record(FOX_KEY, "unresolved", reason, {})}
    plan = _plan_with([FOX_ROW], {FOX0: (2 * M, "SPR", 1)}, stored)
    assert plan.attributions_by_status == {"attributed": 0, "unresolved": 1}
    assert plan.unresolved_by_reason[reason] == 1
    assert plan.promotions == 0
    assert plan.events_with_stored_signing_evidence == 1


def test_stored_cache_only_reason_with_empty_evidence_does_not_block_attribution():
    stored = {FOX_KEY: _stored_record(FOX_KEY, "unresolved", "no_salary_rows_for_season", {})}
    plan = _plan_with([FOX_ROW], {FOX0: (2 * M, "SPR", 1)}, stored)
    assert plan.attributions_by_status == {"attributed": 1, "unresolved": 0}
    assert plan.promotions == 1
    assert plan.events_with_stored_signing_evidence == 0
