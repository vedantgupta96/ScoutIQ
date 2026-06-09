from scoutiq.etl import load_contracts
from scoutiq.etl.load_salary_overrides import _read_rows
from scoutiq.etl.load_bbref_contracts import parse_contract_rows


def test_spotrac_team_parser_uses_clean_link_text(monkeypatch):
    html = """
    <table>
      <tr><th>Player</th><th>Pos</th><th>Signed</th><th>Type</th><th>Age</th><th>Start</th><th>End</th><th>Yrs</th><th>Total</th><th>AAV</th></tr>
      <tr>
        <td><a href="https://www.spotrac.com/nba/player/_/id/17829/karl-anthony-towns">Karl-Anthony Towns</a>Towns Karl-Anthony Towns</td>
        <td>C</td><td>2024</td><td>Extension</td><td>26</td><td>2024</td><td>2027</td><td>4</td><td>$220,441,984</td><td>$55,110,496</td>
      </tr>
      <tr>
        <td><a href="https://www.spotrac.com/nba/player/_/id/23618/og-anunoby">OG Anunoby</a>Anunoby OG Anunoby</td>
        <td>SF</td><td>2024</td><td>Free Agent</td><td>26</td><td>2024</td><td>2028</td><td>5</td><td>$212,500,000</td><td>$42,500,000</td>
      </tr>
    </table>
    """
    monkeypatch.setattr(load_contracts, "_get", lambda url, cache_key: html)

    rows = load_contracts.scrape_team("new-york-knicks")

    assert [(row["full_name"], row["spotrac_id"]) for row in rows] == [
        ("Karl-Anthony Towns", "17829"),
        ("OG Anunoby", "23618"),
    ]


def test_contract_table_uses_cash_fallback_when_cap_hit_blank():
    html = """
    <table>
      <tr>
        <th>Year</th><th></th><th>Age</th><th>Status</th>
        <th>Cap Hit Annual</th><th>Cap % League Cap</th>
        <th>Apron Salary</th><th>Luxury Tax</th><th>Tax % League Tax</th>
        <th>Cash Annual</th><th>Cash Guaranteed</th><th>Cash Cumulative</th>
      </tr>
      <tr>
        <td>2025-26</td><td></td><td>24</td><td></td>
        <td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>
        <td>$85,300</td><td>$85,300</td><td>$85,300</td>
      </tr>
    </table>
    """
    soup = load_contracts.BeautifulSoup(html, "html5lib")

    rows = load_contracts._parse_contract_table(soup.find("table"))

    assert rows[0]["season"] == "2025-26"
    assert rows[0]["aav"] == 85_300
    assert rows[0]["cap_pct"] is None


def test_player_matcher_handles_known_source_aliases():
    index = {
        load_contracts._normalize("Bones Hyland"): 1,
        load_contracts._normalize("Cam Thomas"): 2,
        load_contracts._normalize("Herbert Jones"): 3,
        load_contracts._normalize("Nic Claxton"): 4,
        load_contracts._normalize("Ronald Holland II"): 5,
        load_contracts._normalize("Svi Mykhailiuk"): 6,
    }

    assert load_contracts._match_player("Nah'Shon Hyland", index) == 1
    assert load_contracts._match_player("Cameron Thomas", index) == 2
    assert load_contracts._match_player("Herb Jones", index) == 3
    assert load_contracts._match_player("Nicolas Claxton", index) == 4
    assert load_contracts._match_player("Ron Holland II", index) == 5
    assert load_contracts._match_player("Sviatoslav Mykhailiuk", index) == 6


def test_bbref_contract_parser_reads_current_salary_table():
    html = """
    <table>
      <thead>
        <tr><th>Rk</th><th>Player</th><th>Tm</th><th>2025-26</th><th>2026-27</th><th>Guaranteed</th></tr>
      </thead>
      <tbody>
        <tr><td>171</td><td>Jaden Ivey</td><td>CHI</td><td>$10,107,163</td><td></td><td>$10,107,163</td></tr>
        <tr><td>999</td><td>Two-Way Missing</td><td>IND</td><td></td><td>$85,300</td><td>$85,300</td></tr>
      </tbody>
    </table>
    """

    rows = parse_contract_rows(html, "2025-26")

    assert rows == [{
        "full_name": "Jaden Ivey",
        "team": "CHI",
        "years": [{"season": "2025-26", "aav": 10_107_163}],
    }]


def test_salary_override_seed_contains_source_confirmed_blanks():
    rows = _read_rows(load_contracts.settings.DATA_DIR / "current_salary_overrides.csv", "2025-26")

    by_name = {row["full_name"]: row for row in rows}
    assert by_name["Ethan Thompson"]["salary"] == "508416"
    assert by_name["Javon Small"]["salary"] == "636434"
