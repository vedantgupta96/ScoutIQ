from scoutiq.etl import load_contracts


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
