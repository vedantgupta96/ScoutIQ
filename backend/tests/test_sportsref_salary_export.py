from pathlib import Path

import pytest

from scoutiq.sources.sportsref_salary_export import (
    ExportFormatError,
    parse_export,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sportsref"


@pytest.fixture(scope="module")
def parsed():
    return parse_export((FIXTURES / "contracts_export.html").read_text(encoding="utf-8"))


def test_seasons_read_from_header(parsed):
    assert parsed.seasons == ["2026-27", "2027-28", "2028-29", "2029-30", "2030-31", "2031-32"]


def test_thead_row_skipped_and_ordinals_in_document_order(parsed):
    assert [r.bbref_id for r in parsed.rows] == [
        "jamesle01", "tatumja01", "lillada01", "lillada01", "badcsk01", "unkcls01",
    ]
    assert [r.row_ordinal for r in parsed.rows] == [0, 1, 2, 3, 4, 5]


def test_lebron_values_option_and_blanks(parsed):
    r = parsed.rows[0]
    assert (r.team_abbr, r.player_name, r.source_rank) == ("PHI", "LeBron James", 1)
    assert r.years[0].amount == 3876529 and r.years[0].option is None
    assert r.years[1].amount == 4070355 and r.years[1].option == "player_option"
    assert all(y.amount is None and y.blank for y in r.years[2:])
    assert r.remaining_guaranteed == 3876529


def test_team_option_marker(parsed):
    assert parsed.rows[1].years[1].option == "team_option"


def test_explicit_zero_is_not_blank(parsed):
    por = parsed.rows[3]
    assert por.years[1].amount == 0 and por.years[1].blank is False
    assert por.years[2].amount is None and por.years[2].blank is True


def test_multi_row_player_kept_as_two_rows(parsed):
    lillard = [r for r in parsed.rows if r.bbref_id == "lillada01"]
    assert [r.team_abbr for r in lillard] == ["MIL", "POR"]
    assert lillard[0].years[0].amount == 22400000 and lillard[1].years[0].amount == 11000000


def test_problems_recorded(parsed):
    joined = "\n".join(parsed.problems)
    assert "csk 1000001 disagrees" in joined
    assert "unknown cell class 'salary-xx'" in joined
    assert "missing data-append-csv" in joined
    assert parsed.skipped_rows == 1
    unk = parsed.rows[5].years[0]
    assert unk.option is None and unk.amount == 2000000
    assert unk.uncertain == "unknown_marker:salary-xx"
    assert parsed.rows[4].years[0].amount == 1000001


def test_malformed_header_raises():
    html = (FIXTURES / "malformed_header.html").read_text(encoding="utf-8")
    with pytest.raises(ExportFormatError):
        parse_export(html)


def test_missing_remain_gtd_raises():
    html = (FIXTURES / "contracts_export.html").read_text(encoding="utf-8").replace(
        'data-stat="remain_gtd" data-tip', 'data-stat="other" data-tip'
    )
    with pytest.raises(ExportFormatError):
        parse_export(html)


def test_non_consecutive_seasons_raise():
    html = (FIXTURES / "contracts_export.html").read_text(encoding="utf-8").replace(
        'aria-label="2028-29" data-stat="y3">2028-29', 'aria-label="2029-30" data-stat="y3">2029-30'
    )
    with pytest.raises(ExportFormatError):
        parse_export(html)


def test_missing_team_cell_is_a_problem_and_row_kept():
    html = (FIXTURES / "contracts_export.html").read_text(encoding="utf-8").replace(
        '<td class="left " data-stat="team_id"><a href="/teams/BOS/2027.html">BOS</a></td>', ""
    )
    result = parse_export(html)
    tatum = next(r for r in result.rows if r.bbref_id == "tatumja01")
    assert tatum.team_abbr == ""
    assert any("tatumja01" in p and "team_id" in p for p in result.problems)


def _variant(old, new):
    html = (FIXTURES / "contracts_export.html").read_text(encoding="utf-8")
    assert old in html
    return parse_export(html.replace(old, new, 1))


def test_non_numeric_cell_is_uncertain_not_blank():
    result = _variant(
        '<td class="right salary-pl" data-stat="y2" csk="4070355">$4,070,355</td>',
        '<td class="right " data-stat="y2">TBD</td>',
    )
    cell = result.rows[0].years[1]
    assert cell.amount is None and cell.blank is False and "TBD" in cell.uncertain
    assert any("non-numeric salary value 'TBD'" in p for p in result.problems)


def test_conflicting_option_markers_are_uncertain():
    result = _variant(
        '<td class="right salary-pl" data-stat="y2"', '<td class="right salary-pl salary-tm" data-stat="y2"'
    )
    cell = result.rows[0].years[1]
    assert cell.option is None and cell.uncertain == "conflicting option markers"
    assert any("conflicting option markers" in p for p in result.problems)
