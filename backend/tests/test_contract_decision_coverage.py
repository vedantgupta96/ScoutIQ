import dataclasses
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from scoutiq.etl import check_contract_decision_coverage as probe
from scoutiq.etl.check_contract_decision_coverage import (
    BbrefPage,
    CapRow,
    ProbeInputs,
    SeasonRow,
    SpotracPage,
    StoredContract,
    build_report,
    main,
)
from scoutiq.sources import contract_events as ce
from scoutiq.sources.contract_events import (
    DraftInfo,
    classify_transaction,
    league_year,
    parse_bbref_salary_rows,
    parse_bbref_transactions,
    parse_draft,
    parse_spotrac_contracts,
    parse_spotrac_player_name,
    season_label,
    signing_phase,
)

FIXTURES = Path(__file__).parent / "fixtures" / "contract_decisions"
BBREF_HTML = (FIXTURES / "bbref_player.html").read_text(encoding="utf-8")
SPOTRAC_HTML = (FIXTURES / "spotrac_player.html").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Drafted by the Miami Heat in the 1st round (14th pick) of the 2017 NBA Draft.", "draft"),
        ("Signed a multi-year contract with the Miami Heat.", "standard"),
        ("Re-signed with the New York Knicks.", "standard"),
        ("Signed a contract extension with the Miami Heat.", "extension"),
        ("Re-signed to a contract extension with the Miami Heat.", "extension"),
        ("Converted from a two-way contract with the Miami Heat.", "conversion"),
        ("Signed a two-way contract with the Miami Heat.", "two_way"),
        ("Signed an Exhibit 10 contract with the Miami Heat.", "exhibit"),
        ("Signed a substitution contract with the Miami Heat.", "substitution"),
        ("Signed a contract for the rest of the season with the Miami Heat.", "rest_of_season"),
        (
            "Signed two 10-day contracts with the Miami Heat, then signed a contract for the rest of the season.",
            "rest_of_season",
        ),
        ("Signed a 10-day contract with the Miami Heat.", "ten_day"),
        ("Waived by the Miami Heat.", "waived"),
        ("Released by the Miami Heat.", "released"),
        ("Traded by the Miami Heat to the Chicago Bulls for Pat Placeholder.", "traded"),
        ("As part of a 3-team trade, traded to the Chicago Bulls.", "traded"),
        ("Claimed on waivers by the Chicago Bulls from the Miami Heat.", "claimed"),
        ("Not re-signed by Chicago Bulls; 10-day contract expires.", "other"),
        ("Assigned to the Sioux Falls Skyforce of the G-League.", "other"),
    ],
)
def test_classify_transaction(text, kind):
    assert classify_transaction(text) == kind


def test_league_year_and_season_label():
    assert league_year(date(2019, 6, 30)) == 2018
    assert league_year(date(2019, 7, 1)) == 2019
    assert league_year(date(2021, 1, 15)) == 2020
    assert league_year(date(2020, 7, 15)) == 2019
    assert league_year(date(2020, 10, 11)) == 2019
    assert league_year(date(2020, 10, 12)) == 2020
    assert league_year(date(2020, 11, 28)) == 2020
    assert league_year(date(2021, 7, 20)) == 2020
    assert league_year(date(2021, 7, 21)) == 2021
    assert season_label(2024) == "2024-25"
    assert season_label(1999) == "1999-00"


def test_signing_phase():
    assert signing_phase(date(2019, 7, 6)) == "offseason"
    assert signing_phase(date(2019, 10, 21)) == "offseason"
    assert signing_phase(date(2019, 10, 22)) == "in_season"
    assert signing_phase(date(2020, 12, 1)) == "offseason"
    assert signing_phase(date(2020, 12, 22)) == "in_season"
    assert signing_phase(date(2021, 1, 20)) == "in_season"
    assert signing_phase(date(2030, 8, 1)) == "offseason"
    assert signing_phase(date(2030, 11, 1)) == "in_season"


def test_spotrac_name_formats():
    assert parse_spotrac_player_name(
        "<title>Chris Manon Contract, Salary &amp; Cap Hit 2026 | Spotrac</title>"
    ) == "Chris Manon Contract, Salary &amp; Cap Hit 2026".split(" Contract")[0]
    assert parse_spotrac_player_name(
        "<title>Chris Manon Contract, Salary & Cap Hit 2026 | Spotrac</title>"
        '<h1 id="x" class="h3">\n  Chris   <span>Manon</span> </h1>'
    ) == "Chris Manon"
    assert parse_spotrac_player_name("<title>Hayden Gray | NBA Contracts & Salaries | Spotrac.com</title><h1> </h1>") == "Hayden Gray"
    assert parse_spotrac_player_name("<html></html>") is None


def _team(html_text: str) -> str | None:
    return parse_bbref_transactions(
        f'<p class="transaction "><strong>July 1, 2019</strong>: {html_text}</p>'
    )[0].team


def test_team_extraction():
    assert _team("Signed a multi-year contract with the <a href='/x'>Miami Heat</a>.") == "Miami Heat"
    assert _team("Re-signed with the New York Knicks.") == "New York Knicks"
    assert _team("Traded by the Miami Heat to the Chicago Bulls for Pat Placeholder.") == "Chicago Bulls"
    assert _team("Claimed on waivers by the Chicago Bulls from the Miami Heat.") == "Chicago Bulls"
    assert _team("Assigned to the Sioux Falls Skyforce of the G-League.") is None
    assert _team("Signed a contract.") is None


def test_parse_draft():
    assert parse_draft(
        "Drafted by the Miami Heat in the 1st round (14th pick) of the 2017 NBA Draft."
    ) == DraftInfo(2017, 1, 14)
    assert parse_draft("Drafted by the Miami Heat in the 2nd round of the 2009 NBA Draft.") == DraftInfo(
        2009, 2, None
    )
    assert parse_draft("Signed a contract with the Miami Heat.") is None


def test_parse_bbref_fixture():
    txns = parse_bbref_transactions(BBREF_HTML)
    assert [t.kind for t in txns] == [
        "draft",
        "standard",
        "traded",
        "ten_day",
        "extension",
        "two_way",
        "other",
    ]
    assert txns[0].date == date(2017, 6, 20)
    assert txns[2].team == "Riverton Owls"
    assert txns[4].text == "Signed a contract extension with the Riverton Owls."
    assert txns[5].date is None
    assert txns[5].team == "Riverton Owls"

    rows = parse_bbref_salary_rows(BBREF_HTML)
    assert [(r.season, r.team, r.salary) for r in rows] == [
        ("2017-18", "Springfield Foxes", 2_000_000),
        ("2018-19", "Springfield Foxes", 2_100_000),
        ("2018-19", "Riverton Owls", 900_000),
    ]
    assert parse_bbref_transactions("<html></html>") == []
    assert parse_bbref_salary_rows("<html></html>") == []


def test_parse_spotrac_fixture():
    assert parse_spotrac_player_name(SPOTRAC_HTML) == "Hayden Test"
    contracts = parse_spotrac_contracts(SPOTRAC_HTML)
    assert [c.first_season for c in contracts] == ["2025-26", "2022-23", "2019-20"]

    cur, ext, rookie = contracts
    assert cur.is_current and not cur.is_upcoming
    assert cur.type_label == "rest-of-season"
    assert (cur.years, cur.total_value, cur.aav) == (2, 2_000_000, 1_000_000)
    assert (cur.gtd_at_sign, cur.total_gtd) == (10_000, 10_000)
    assert cur.signed_using == "minimum"
    assert (cur.fa_year, cur.fa_status) == (2027, "rfa")
    assert (cur.start_year, cur.end_year) == (2025, 2026)

    assert ext.type_label == "veteran extension"
    assert ext.gtd_at_sign is None
    assert ext.total_gtd == 20_000_000
    assert ext.signed_using == "bird"
    assert ext.fa_status == "ufa"
    assert not ext.is_current

    assert rookie.type_label == "rookie"
    assert rookie.signed_using == "rookie-scale"
    assert rookie.total_gtd is None


def test_status_flags():
    html = (
        '<div class="contract-wrapper"><h2><span class="years">2026-2027 '
        '<small>Veteran Extension <strong>(UPCOMING EXTENSION)</strong></small></span></h2></div>'
        '<div class="contract-wrapper"><h2><span class="years">2026-2027 '
        '<small>Free Agent <strong>(PENDING)</strong></small></span></h2></div>'
    )
    a, b = parse_spotrac_contracts(html)
    assert (a.type_label, a.is_upcoming, a.is_current) == ("veteran extension", True, False)
    assert (b.type_label, b.is_upcoming) == ("free agent", True)


def test_normalize_and_form_classes():
    n = ce.normalize_signed_using
    assert n("Minimum") == "minimum"
    assert n("Bird Rights") == "bird"
    assert n("Early Bird Rights") == "early-bird"
    assert n("Non-Bird Rights") == "non-bird"
    assert n("Non-Taxpayer MLE") == "non-taxpayer-mle"
    assert n("non-taxpayer-mid-level-exception") == "non-taxpayer-mle"
    assert n("Taxpayer MLE") == "taxpayer-mle"
    assert n("room-mid-level-exception") == "room-mle"
    assert n("bi-annual-exception") == "bi-annual"
    assert n("rookie-scale-exception") == "rookie-scale"
    assert n("second-round-exception") == "second-round"
    assert n("cap-space") == "cap-space"
    assert n("  ") is None and n(None) is None
    assert n("Hardship") == "hardship"

    f = ce.spotrac_form_class
    assert f("maximum veteran extension") == "extension"
    assert f("extend-and-trade") == "extension"
    assert f("two-way") == "two_way"
    assert f("exhibit-10") == "short_form"
    assert f("ten-day") == "short_form"
    assert f("camp invite") == "short_form"
    assert f("free agent") == "standard_form"

    e = ce.event_form_class
    assert [e(k) for k in ("standard", "rest_of_season", "conversion")] == ["standard_form"] * 3
    assert e("two_way") == "two_way"
    assert [e(k) for k in ("ten_day", "exhibit", "substitution")] == ["short_form"] * 3
    assert e("extension") == "extension"


def _fmt(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def _page(slug: str, lines: list[tuple[date | str, str]], salary_rows=None) -> BbrefPage:
    html = "".join(
        f'<p class="transaction "><strong>{d if isinstance(d, str) else _fmt(d)}</strong>: {text}</p>'
        for d, text in lines
    )
    return BbrefPage(slug, parse_bbref_transactions(html), salary_rows or [])


def _block(years: str, label: str, terms="", avg="", using="", fa="", gtd="", total_gtd="") -> str:
    cells = "".join(
        f'<div class="cell"><div class="label">{k}:</div><div class="value">{v}</div></div>'
        for k, v in (
            ("Contract Terms", terms),
            ("Average Salary", avg),
            ("GTD at Sign", gtd),
            ("Total GTD", total_gtd),
            ("Signed Using", using),
            ("Free Agent", fa),
        )
    )
    return (
        f'<div class="contract-wrapper"><h2><span class="years">{years} <small>{label}</small>'
        f'</span></h2><div class="contract-details">{cells}</div></div>'
    )


def _spotrac(file: str, name: str, *blocks: str) -> SpotracPage:
    html = "".join(blocks)
    return SpotracPage(file, name, parse_spotrac_contracts(html), False)


SEASONS = ["2018-19", "2019-20", "2020-21", "2021-22"]
M = 1_000_000


def _inputs() -> ProbeInputs:
    pages = [
        _page(
            "alphaan01",
            [
                (date(2017, 6, 22), "Drafted by the Foxes in the 1st round (3rd pick) of the 2017 NBA Draft."),
                (date(2017, 7, 1), "Signed a multi-year contract with the Foxes."),
                (date(2020, 10, 20), "Signed a contract extension with the Foxes."),
            ],
        ),
        _page("betabo01", [(date(2019, 7, 6), "Signed a contract with the Owls.")]),
        _page(
            "gammacy01",
            [
                (date(2019, 7, 1), "Signed a contract with the Hawks."),
                (date(2019, 7, 20), "Signed a contract with the Hawks."),
            ],
            salary_rows=[
                ce.SalaryRow("2019-20", "Hawks", 3 * M),
                ce.SalaryRow("2019-20", "Kites", 2 * M),
            ],
        ),
        _page(
            "deltade01",
            [
                (date(2019, 7, 1), "Signed a contract with the Hawks."),
                (date(2019, 7, 1), "Signed a contract with the Hawks."),
            ],
        ),
        _page(
            "epsilonel01",
            [
                (date(2020, 1, 10), "Signed a 10-day contract with the Owls."),
                (date(2020, 12, 25), "Signed a two-way contract with the Owls."),
            ],
        ),
        _page("zetafa01", [(date(2020, 11, 28), "Signed a contract with the Foxes.")]),
        _page(
            "etagu01",
            [
                (date(2019, 6, 20), "Drafted by the Owls in the 1st round (10th pick) of the 2019 NBA Draft."),
                (date(2019, 7, 1), "Signed a multi-year contract with the Owls."),
            ],
        ),
        _page("thetaha01", [(date(2020, 11, 1), "Signed a contract extension with the Hawks.")]),
        _page(
            "iotaia01",
            [
                (date(2019, 7, 3), "Signed a contract with the Owls."),
                ("Someday 2019", "Signed a contract with the Owls."),
            ],
        ),
        _page("nobody01", []),
    ]
    spotrac = [
        _spotrac(
            "player_1.html",
            "Ann Alpha",
            _block("2017-2021", "Rookie", "4 yr(s) / $40,000,000", "$10,000,000", "rookie-scale-exception"),
            _block("2021-2026", "Rookie Extension", "5 yr(s) / $100,000,000", "$20,000,000", "Bird Rights", "2026 / UFA"),
        ),
        _spotrac(
            "player_2.html",
            "Bob Beta",
            _block("2016-2018", "Free Agent", "2 yr(s) / $2,000,000", "$1,000,000", "Minimum"),
            _block("2019-2022", "Free Agent", "3 yr(s) / $30,000,000", "$10,000,000", "Bird Rights", "2022 / UFA"),
        ),
        _spotrac("player_3.html", "Unknown Person", _block("2019-2020", "Free Agent")),
    ]
    cap = CapRow(100 * M, 25 * M, 30 * M, 35 * M)
    return ProbeInputs(
        seasons=SEASONS,
        bbref_pages=pages,
        spotrac_pages=spotrac,
        xref={
            "alphaan01": 1,
            "betabo01": 2,
            "gammacy01": 3,
            "deltade01": 4,
            "epsilonel01": 5,
            "zetafa01": 6,
            "etagu01": 7,
            "thetaha01": 8,
        },
        players={
            1: ("Ann Alpha", "SF-PF"),
            2: ("Bob Beta", "PG"),
            3: ("Cy Gamma", "C"),
            4: ("Dee Delta", None),
            5: ("Eli Epsilon", "SG"),
            6: ("Fay Zeta", "PF"),
            7: ("Gus Eta", "SF"),
            8: ("Hal Theta", "C"),
        },
        salaries={
            (1, "2021-22"): 20 * M,
            (2, "2019-20"): 10 * M,
            (3, "2019-20"): 5 * M,
            (4, "2019-20"): 1_500_000,
            (6, "2020-21"): 35 * M,
            (7, "2019-20"): 6 * M,
        },
        caps={
            "2019-20": cap,
            "2020-21": cap,
            "2021-22": CapRow(110 * M, 27_500_000, 33 * M, 38_500_000),
        },
        player_seasons={
            (1, "2019-20"): SeasonRow(22, 60, 1500.0, True),
            (2, "2018-19"): SeasonRow(25, 70, 2000.0, True),
            (3, "2018-19"): SeasonRow(30, 10, 100.0, True),
            (6, "2019-20"): SeasonRow(31, 60, 1500.0, True),
            (7, "2018-19"): SeasonRow(19, 50, 900.0, True),
        },
        contracts=[
            StoredContract(2, "2019-20", 3, "spotrac", 30 * M, None),
            StoredContract(1, "2021-22", 5, "spotrac", 100 * M, None),
            StoredContract(5, "2020-21", 1, "spotrac", None, None),
            StoredContract(3, "2020-21", 1, "spotrac", None, None),
            StoredContract(99, "2019-20", 1, "spotrac", None, None),
        ],
        inventory={"row_counts": [{"table_name": "players", "n": 8}]},
    )


@pytest.fixture(scope="module")
def report():
    return build_report(_inputs())


def _season_row(rows, season):
    return next(r for r in rows if r["season"] == season)


def test_funnel_one_season(report):
    row = _season_row(report["funnel_standard_form"]["by_season"], "2019-20")
    assert row == {
        "season": "2019-20",
        "events": 5,
        "unambiguous": 3,
        "has_salary": 5,
        "salary_single_team": 3,
        "salary_multi_team": 2,
        "has_cap": 5,
        "has_prior_row": 4,
        "has_prior_bpm": 4,
        "prior_qualified": 2,
        "usable": 2,
        "usable_unconstrained": 1,
        "usable_unconstrained_offseason": 1,
        "usable_with_exact_terms": 1,
        "usable_unconstrained_with_exact_terms": 1,
    }
    total = report["funnel_standard_form"]["total"]
    assert (total["events"], total["usable"], total["usable_unconstrained"]) == (6, 3, 1)


def test_extension_not_a_standard_form_decision(report):
    fun = report["funnel_standard_form"]["by_season"]
    assert _season_row(fun, "2021-22")["events"] == 0
    assert _season_row(fun, "2020-21")["events"] == 1
    assert [r["season"] for r in fun] == ["2019-20", "2020-21", "2021-22"]


def test_extension_linking_and_unresolved(report):
    ext = report["extensions"]
    assert ext["total"] == {
        "events": 2,
        "first_paid_season_resolved": 1,
        "has_salary": 1,
        "salary_multi_team": 0,
        "has_cap": 1,
        "has_prior_bpm": 1,
        "usable": 1,
        "usable_with_exact_terms": 1,
        "rookie_extension": 1,
        "veteran_extension": 1,
        "at_max": 0,
    }
    assert ext["gap_seasons_distribution"] == {"1": 1}
    assert _season_row(ext["by_signing_season"], "2020-21")["events"] == 2
    assert report["dedup"]["spotrac_link_extension"] == {
        "linked": 1,
        "contract_unlinked": 0,
        "event_unlinked": 0,
    }
    assert report["dedup"]["events_on_players_without_spotrac_page"] == 8


def test_duplicate_collapse_and_candidate_key(report):
    assert report["dedup"]["duplicates_collapsed"] == 1
    assert report["sources"]["bbref"]["duplicates_collapsed"] == 1
    assert report["candidate_key"] == {
        "definition": "player_id:signing_date:kind:team",
        "n_events": 12,
        "n_distinct_keys": 11,
        "collisions": 1,
        "duplicates_identical": 1,
        "duplicates_text_variant": 0,
    }


def test_ambiguity(report):
    dedup = report["dedup"]
    assert dedup["ambiguous_events"] == 2
    assert dedup["multi_team_salary_events"] == 2
    assert dedup["multi_team_salary_events_otherwise_usable"] == 0
    assert dedup["multi_team_salary_recoverable_by_row_sum"] == 0
    assert sum(dedup["multi_team_salary_otherwise_usable_by_cause"].values()) == 0
    assert dedup["ambiguous_player_seasons"] == 1
    assert dedup["ambiguous_resolvable_by_per_team_salary"] == 2
    assert report["sources"]["bbref"]["multi_team_salary"] == {
        "db_equals_sum": 1,
        "db_equals_max_row": 0,
        "db_equals_other_row": 0,
        "db_matches_none": 0,
        "db_missing": 0,
        "player_seasons_with_multiple_team_rows": 1,
    }


def test_structure_rules(report):
    all_struct = report["structure"]["all_in_window"]["structure"]
    assert all_struct == {
        "max": 1,
        "no_constraint_identified": 3,
        "near_minimum": 1,
        "rookie_extension": 1,
        "rookie_scale": 1,
        "ten_day": 1,
        "two_way": 1,
        "veteran_extension": 1,
    }
    usable = report["structure"]["usable_standard_form"]
    assert usable["structure"] == {"no_constraint_identified": 1, "max": 1, "rookie_scale": 1}
    assert usable["tier"] == {"censored": 1, "no_constraint_identified": 1, "mechanical": 1}
    tiers = report["structure"]["all_in_window"]["tier"]
    assert tiers["extension_rules"] == 2
    assert tiers["no_constraint_identified"] == 3
    assert report["structure"]["by_season_usable_standard_form"] == {
        "2019-20": {"no_constraint_identified": 1, "rookie_scale": 1},
        "2020-21": {"max": 1},
        "2021-22": {},
    }
    other = _season_row(report["funnel_other_forms"], "total")
    assert (other["two_way_events"], other["short_form_events"]) == (1, 1)


def test_spotrac_linking_and_proxies(report):
    assert report["dedup"]["spotrac_link_non_extension"] == {
        "linked": 2,
        "ambiguous": 0,
        "event_only": 0,
        "contract_only": 1,
    }
    sp = report["sources"]["spotrac"]
    assert (sp["pages_matched"], sp["pages_unmatched"], sp["pages_ambiguous"]) == (2, 1, 0)
    assert report["proxy_validation"]["near_minimum_vs_signed_using_minimum"] == {
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "tn": 1,
    }
    bd = report["breakdowns"]["usable_unconstrained"]
    assert bd["n"] == 1
    assert bd["age_bucket"]["23-25"] == 1
    assert bd["position"] == {"PG": 1}


def test_bbref_source_counts(report):
    b = report["sources"]["bbref"]
    assert b["pages"] == 10
    assert b["pages_without_transactions"] == 1
    assert b["pages_without_verified_xref"] == 2
    assert b["signing_events_on_unmatched_pages"] == 2
    assert b["unparseable_dates"] == 1


def test_multi_team_salary_not_usable():
    base = _inputs()
    bob = base.bbref_pages[1]
    rows = [ce.SalaryRow("2019-20", "Owls", 6 * M), ce.SalaryRow("2019-20", "Foxes", 4 * M)]
    pages = [dataclasses.replace(bob, salary_rows=rows) if p is bob else p for p in base.bbref_pages]
    rep_ = build_report(dataclasses.replace(base, bbref_pages=pages))
    row = _season_row(rep_["funnel_standard_form"]["by_season"], "2019-20")
    assert (row["has_salary"], row["salary_single_team"], row["salary_multi_team"]) == (5, 2, 3)
    assert row["usable"] == 1
    assert rep_["dedup"]["multi_team_salary_events"] == 3
    assert rep_["dedup"]["multi_team_salary_events_otherwise_usable"] == 1
    assert rep_["constraint_evidence"]["n"] == 0


def test_multi_team_extension_not_usable():
    base = _inputs()
    ann = base.bbref_pages[0]
    rows = [ce.SalaryRow("2021-22", "Foxes", 10 * M), ce.SalaryRow("2021-22", "Owls", 10 * M)]
    pages = [dataclasses.replace(ann, salary_rows=rows) if p is ann else p for p in base.bbref_pages]
    total = build_report(dataclasses.replace(base, bbref_pages=pages))["extensions"]["total"]
    assert (total["has_salary"], total["salary_multi_team"], total["usable"]) == (1, 1, 0)


def test_multi_team_recoverability_causes():
    base = _inputs()
    owls = "Signed a contract with the Owls."
    pages = [
        _page("pa01", [(date(2019, 7, 10), owls), (date(2019, 8, 1), "Signed a 10-day contract with the Owls.")]),
        _page("pb01", [(date(2019, 7, 10), owls), (date(2019, 8, 1), "Waived by the Owls.")]),
        _page("pc01", [(date(2019, 7, 10), owls), (date(2019, 8, 1), "Traded by the Owls to the Foxes for Pat Placeholder.")]),
        _page("pd01", [(date(2019, 7, 10), owls)]),
    ]
    rows = [ce.SalaryRow("2019-20", "Owls", 3 * M), ce.SalaryRow("2019-20", "Foxes", 2 * M)]
    pages = [dataclasses.replace(p, salary_rows=rows) for p in pages]
    pids = {"pa01": 31, "pb01": 32, "pc01": 33, "pd01": 34}
    inputs = dataclasses.replace(
        base,
        bbref_pages=pages,
        xref=pids,
        players={pid: (f"Player {pid}", None) for pid in pids.values()},
        spotrac_pages=[],
        salaries={(pid, "2019-20"): 5 * M for pid in pids.values()},
        player_seasons={(pid, "2018-19"): SeasonRow(25, 60, 1500.0, True) for pid in pids.values()},
        contracts=[],
    )
    dedup = build_report(inputs)["dedup"]
    assert dedup["multi_team_salary_events"] == 4
    assert dedup["multi_team_salary_events_otherwise_usable"] == 4
    assert dedup["multi_team_salary_otherwise_usable_by_cause"] == {
        "other_signing_same_season": 1,
        "waiver_or_release_same_season": 1,
        "trade_only": 1,
        "unexplained": 1,
    }
    assert list(dedup["multi_team_salary_otherwise_usable_by_cause"]) == [
        "other_signing_same_season",
        "waiver_or_release_same_season",
        "trade_only",
        "unexplained",
    ]
    assert dedup["multi_team_salary_recoverable_by_row_sum"] == 1


def test_constraint_evidence(report):
    assert report["constraint_evidence"] == {
        "n": 1,
        "with_spotrac_link": 1,
        "signed_using_counts": {"bird": 1},
        "signed_using_capped": 0,
        "signed_using_open": 1,
        "signed_using_unknown": 0,
        "rfa_at_signing_known": 0,
        "fa_status_known": 0,
    }
    keys = list(report)
    assert keys.index("constraint_evidence") == keys.index("proxy_validation") + 1


def _dup_inputs(lines) -> ProbeInputs:
    base = _inputs()
    return dataclasses.replace(
        base,
        bbref_pages=[_page("dupli01", lines)],
        xref={"dupli01": 20},
        players={20: ("Dup Li", None)},
        spotrac_pages=[],
        salaries={},
        player_seasons={},
        contracts=[],
    )


def test_candidate_key_variants_and_teams():
    d = date(2019, 7, 6)
    variant = build_report(
        _dup_inputs(
            [(d, "Signed as a free agent with the Owls."), (d, "Signed a multi-year contract with the Owls.")]
        )
    )
    assert variant["candidate_key"]["duplicates_identical"] == 0
    assert variant["candidate_key"]["duplicates_text_variant"] == 1
    assert variant["candidate_key"]["collisions"] == 1
    assert variant["dedup"]["duplicates_collapsed"] == 1
    assert variant["funnel_standard_form"]["total"]["events"] == 1

    teams = build_report(
        _dup_inputs([(d, "Signed a contract with the Owls."), (d, "Signed a contract with the Hawks.")])
    )
    assert teams["candidate_key"]["collisions"] == 0
    assert teams["funnel_standard_form"]["total"]["events"] == 2
    assert teams["funnel_standard_form"]["total"]["unambiguous"] == 0
    assert teams["dedup"]["ambiguous_events"] == 2


@pytest.mark.parametrize(
    "gtd,expected",
    [
        ("$30,000,000", (1, 0, 0)),
        ("$5,000,000", (0, 1, 0)),
        ("$0", (0, 0, 1)),
    ],
)
def test_guarantee_and_option_coverage(gtd, expected):
    base = _inputs()
    bob = _spotrac(
        "player_2.html",
        "Bob Beta",
        _block(
            "2019-2022", "Free Agent", "3 yr(s) / $30,000,000", "$10,000,000", "Bird Rights", "2022 / UFA", gtd=gtd
        ),
    )
    contracts = [
        dataclasses.replace(base.contracts[0], year_rows=3, has_player_option=True),
        *base.contracts[1:],
    ]
    spotrac = [bob if p.file == "player_2.html" else p for p in base.spotrac_pages]
    rep_ = build_report(dataclasses.replace(base, spotrac_pages=spotrac, contracts=contracts))
    fm = rep_["field_missingness"]["standard_form"]
    assert fm["guarantee_split_known"] == 1
    assert (
        fm["fully_guaranteed_at_sign"],
        fm["partially_guaranteed_at_sign"],
        fm["non_guaranteed_at_sign"],
    ) == expected
    assert fm["option_years_stored"] == 1
    assert fm["stored_with_player_option"] == 1
    assert fm["stored_with_team_option"] == 0
    assert fm["stored_with_non_guaranteed_year"] == 0
    assert "option_detail" not in fm
    base_fm = build_report(base)["field_missingness"]["standard_form"]
    assert base_fm["option_years_stored"] == 0


def test_cache_fetched_range_defaults(report):
    assert report["sources"]["bbref"]["cache_fetched_range"] == {"min": None, "max": None}
    assert report["sources"]["spotrac"]["cache_fetched_range"] == {"min": None, "max": None}


def test_audit_extension_window():
    inputs = _inputs()
    inputs = dataclasses.replace(
        inputs,
        contracts=[StoredContract(1, "2024-25", 1, "spotrac", None, None)],
    )
    total = build_report(inputs)["stored_contract_audit"]["total"]
    assert total["extension_signed_earlier"] == 0
    assert total["no_event_found"] == 1


def test_missing_reasons():
    base = _inputs()
    owls = "Signed a contract with the Owls."
    extra = [
        _page("ivyka01", [(date(2019, 7, 10), owls), (date(2019, 10, 1), "Waived by the Owls.")]),
        _page(
            "jayla01",
            [(date(2019, 7, 11), owls)],
            salary_rows=[ce.SalaryRow("2018-19", "Owls", 1)],
        ),
        _page("kimmu01", [(date(2019, 7, 12), owls)]),
        _page("leenu01", [(date(2019, 7, 13), owls), (date(2019, 12, 1), "Waived by the Owls.")]),
    ]
    inputs = dataclasses.replace(
        base,
        bbref_pages=base.bbref_pages + extra,
        xref={**base.xref, "ivyka01": 9, "jayla01": 10, "kimmu01": 11, "leenu01": 12},
        players={
            **base.players,
            9: ("Ivy Kappa", None),
            10: ("Jay Lambda", None),
            11: ("Kim Mu", None),
            12: ("Lee Nu", None),
        },
        player_seasons={**base.player_seasons, (10, "2016-17"): SeasonRow(25, 60, 1500.0, True)},
    )
    reasons = build_report(inputs)["missing_reasons"]
    assert reasons == {
        "first_year_salary": {"n": 4, "no_salary_rows_on_page": 2, "other": 1, "waived_before_opener": 1},
        "prior_production": {
            "n": 5,
            "before_data_window": 0,
            "gap_before_signing": 1,
            "no_earlier_nba_season": 4,
        },
        "camp_deals_suspected": 1,
        "camp_deals_suspected_by_season": {"2019-20": 1},
        "camp_deals_suspected_usable": 0,
    }
    keys = list(build_report(inputs))
    assert keys.index("missing_reasons") == keys.index("field_missingness") + 1


def test_stored_contract_audit(report):
    audit = report["stored_contract_audit"]
    assert audit["total"] == {
        "extension_signed_earlier": 1,
        "no_bbref_page": 1,
        "no_event_found": 1,
        "standard_signing_same_season": 1,
        "two_way_or_short_form_same_season": 1,
    }
    assert audit["by_season_start"]["2020-21"]["no_event_found"] == 1
    assert audit["events_without_stored_contract"] == [
        {"season": "2019-20", "standard_form_events": 5, "without_stored_contract": 4},
        {"season": "2020-21", "standard_form_events": 1, "without_stored_contract": 1},
        {"season": "2021-22", "standard_form_events": 0, "without_stored_contract": 0},
    ]


def test_json_and_determinism():
    first = build_report(_inputs())
    json.dumps(first)
    assert first == build_report(_inputs())
    assert probe.render_text(first)


def test_modules_are_offline():
    for mod in (probe, ce):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        for banned in ("import requests", "urllib", "httpx", "socket"):
            assert banned not in src


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_cache_only_main(tmp_path, capsys):
    shutil.copy(FIXTURES / "bbref_player.html", tmp_path / "fakepl01.html")
    (tmp_path / "spotrac").mkdir()
    shutil.copy(FIXTURES / "spotrac_player.html", tmp_path / "spotrac" / "player_1.html")
    assert main(["--cache-only", "--raw-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "== sources ==" in out
    assert "kind_counts" in out
    assert main(["--cache-only", "--json", "--raw-dir", str(tmp_path)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["sources"]["bbref"]["pages"] == 1
    assert data["sources"]["spotrac"]["contracts_total"] == 3
    assert len(data["sources"]["bbref"]["cache_fetched_range"]["min"]) == 10
    assert len(data["sources"]["spotrac"]["cache_fetched_range"]["max"]) == 10


def test_empty_raw_dir_returns_one(tmp_path):
    assert main(["--cache-only", "--raw-dir", str(tmp_path)]) == 1
