"""Spotrac future-picks parser/resolver: structure, protections, swaps, honest fallbacks."""
from scoutiq.etl.load_draft_pick_ownership import (
    OwnPickLine,
    parse_own_pick_lines,
    resolve_line,
)

KNOWN = {"ATL", "BKN", "CHA", "DAL", "HOU", "MIA", "SAS"}

# Minimal replica of the Spotrac page shape: a heading span per team, then one table
# per round; year header rows span the pick axis, entry cells encode ranges via colspan.
FIXTURE = """
<html><body>
<span>Round 1</span><span>Round 2</span><span class="d-none">Charlotte Hornets</span>
<table>
  <tr><td colspan="31">2027</td></tr>
  <tr><th></th><th>1</th><th>2</th></tr>
  <tr><td class="center"></td><td colspan="30">CHA</td></tr>
  <tr><td class="center"></td><td colspan="2">DAL If 1-2</td><td colspan="28">CHA If 3-30</td></tr>
  <tr><td colspan="31">2028</td></tr>
  <tr><td class="center"></td><td colspan="30">SAS (via HOU)</td></tr>
</table>
<table>
  <tr><td colspan="31">2027</td></tr>
  <tr><td class="center"></td><td colspan="30">CHA Less favorable of BOS and ORL then other to UTA</td></tr>
</table>
<span class="d-none">Dallas Mavericks</span>
<table>
  <tr><td colspan="31">2027</td></tr>
  <tr><td class="center"></td><td colspan="2">DAL If 1-2</td><td colspan="28">CHA If 3-30</td></tr>
  <tr><td colspan="31">2028</td></tr>
  <tr><td class="center"></td><td colspan="30">DAL HOU Or swap with HOU (via HOU swap for DAL)</td></tr>
</table>
<table>
  <tr><td colspan="31">2027</td></tr>
  <tr><td class="center"></td><td colspan="30">DAL</td></tr>
</table>
</body></html>
"""

NAMES = {"Charlotte Hornets": "CHA", "Dallas Mavericks": "DAL"}


def test_parse_takes_first_row_per_year_as_own_pick():
    lines = parse_own_pick_lines(FIXTURE, NAMES)

    keys = {(l.origin_abbr, l.draft_year, l.round) for l in lines}
    # CHA: 2027 + 2028 R1, 2027 R2; DAL: 2027 + 2028 R1, 2027 R2. Mirror rows excluded.
    assert keys == {
        ("CHA", 2027, 1), ("CHA", 2028, 1), ("CHA", 2027, 2),
        ("DAL", 2027, 1), ("DAL", 2028, 1), ("DAL", 2027, 2),
    }
    cha_2027 = next(l for l in lines if (l.origin_abbr, l.draft_year, l.round) == ("CHA", 2027, 1))
    assert cha_2027.segments == [("CHA", 30)]  # not the mirrored DAL row


def _line_for(lines, origin, year, rnd):
    return next(l for l in lines if (l.origin_abbr, l.draft_year, l.round) == (origin, year, rnd))


def test_resolver_handles_the_four_shapes():
    lines = parse_own_pick_lines(FIXTURE, NAMES)

    kept = resolve_line(_line_for(lines, "CHA", 2027, 1), KNOWN)
    assert (kept["owner_abbr"], kept["protected_top"], kept["resolved"]) == ("CHA", None, True)

    traded = resolve_line(_line_for(lines, "CHA", 2028, 1), KNOWN)
    assert (traded["owner_abbr"], traded["resolved"]) == ("SAS", True)
    assert traded["notes"] == "SAS (via HOU)"

    protected = resolve_line(_line_for(lines, "DAL", 2027, 1), KNOWN)
    assert (protected["owner_abbr"], protected["protected_top"], protected["resolved"]) == ("CHA", 2, True)

    swap = resolve_line(_line_for(lines, "DAL", 2028, 1), KNOWN)
    assert (swap["owner_abbr"], swap["swap_abbr"], swap["resolved"]) == ("DAL", "HOU", True)


def test_resolver_keeps_origin_for_conditional_prose():
    lines = parse_own_pick_lines(FIXTURE, NAMES)
    conditional = resolve_line(_line_for(lines, "CHA", 2027, 2), KNOWN)

    assert conditional["resolved"] is False
    assert conditional["owner_abbr"] == "CHA"       # conservative: origin keeps it
    assert "Less favorable" in conditional["notes"]  # verbatim, no force-fit


def test_resolver_ignores_unknown_abbreviations():
    line = OwnPickLine("CHA", 2029, 1, [("XYZ something strange", 30)])
    result = resolve_line(line, KNOWN)
    assert result["resolved"] is False
    assert result["owner_abbr"] == "CHA"
