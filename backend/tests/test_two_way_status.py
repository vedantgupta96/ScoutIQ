"""scrape_team two-way detection: a two-way row is flagged, a standard row is not."""
from scoutiq.etl.load_contracts import scrape_team


# Minimal replica of a Spotrac team contracts table: header + one standard row
# (UFA designation) + one two-way row ("Free Agent Two-Way"). scrape_team reads the
# first table, requires a player link with /id/{n}/{slug} and a numeric years cell.
FIXTURE = """
<html><body><table>
<tr><th>Player</th><th>Pos</th><th>Yr</th><th>Status</th><th>Age</th>
    <th>Start</th><th>End</th><th>Years</th><th>Total</th><th>AAV</th></tr>
<tr>
  <td><a href="/nba/player/_/id/100/jayson-tatum">Jayson Tatum</a></td>
  <td>F</td><td>2026</td><td>UFA / $73.7M</td><td>27</td>
  <td>2024</td><td>2029</td><td>5</td><td>$300,000,000</td><td>$60,000,000</td>
</tr>
<tr>
  <td><a href="/nba/player/_/id/200/amari-williams">Amari Williams</a></td>
  <td>C</td><td>2026</td><td>Free Agent Two-Way</td><td>24</td>
  <td>2026</td><td>2026</td><td>1</td><td>$679,042</td><td>$679,042</td>
</tr>
</table></body></html>
"""


def test_scrape_team_flags_two_way(monkeypatch):
    monkeypatch.setattr("scoutiq.etl.load_contracts._get", lambda url, key: FIXTURE)

    players = {p["full_name"]: p for p in scrape_team("boston-celtics")}

    assert set(players) == {"Jayson Tatum", "Amari Williams"}
    assert players["Amari Williams"]["is_two_way"] is True
    assert players["Jayson Tatum"]["is_two_way"] is False
    # standard fields still parse correctly alongside the new flag
    assert players["Jayson Tatum"]["spotrac_id"] == "100"
    assert players["Amari Williams"]["years"] == 1
