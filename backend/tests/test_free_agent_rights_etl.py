from scoutiq.etl.load_contracts import NBA_TEAM_SLUGS
from scoutiq.etl.load_free_agent_rights import TEAM_ABBREVIATIONS, parse_cap_holds, parse_free_agents


def test_team_slug_map_covers_all_30_teams():
    assert set(TEAM_ABBREVIATIONS) == set(NBA_TEAM_SLUGS)
    assert len(set(TEAM_ABBREVIATIONS.values())) == 30


def test_parse_free_agents_only_accepts_explicit_status():
    html = """<h2>Signed</h2><table><tr><th>Player (8)</th><th>Prev AAV</th><th>Type</th></tr>
    <tr><td><a href='/nba/player/_/id/99/z'>Wrong Table</a></td><td>$1</td><td>UFA / Bird</td></tr></table>
    <h2>Available</h2><table><tr><th> Player (102) </th><th>Prev AAV</th><th>Type</th></tr>
    <tr><td><a href='/nba/player/_/id/11/a'>A Player</a></td><td>$12,000,000</td><td>RFA / Bird</td></tr>
    <tr><td><a href='/nba/player/_/id/12/b'>B Player</a></td><td>$49,000,000</td><td>PLAYER / $49.0M</td></tr></table>"""
    assert parse_free_agents(html) == [{"full_name": "A Player", "source_player_id": "11", "fa_status": "rfa", "bird_rights": "bird", "previous_aav_usd": 12_000_000, "qualifying_offer_usd": None}]


def test_parse_cap_hold_table_associated_with_heading():
    html = """<h2>2026-27 Cap Hold</h2><table><tr><th>Player (4)</th><th>Cap Hit</th><th></th><th></th></tr>
    <tr><td><a href='/nba/player/_/id/11/a'>A Player</a></td><td>$18,500,000</td><td></td><td>Early Bird</td></tr></table>"""
    assert parse_cap_holds(html)[0]["cap_hold_usd"] == 18_500_000
    assert parse_cap_holds(html)[0]["bird_rights"] == "early-bird"
