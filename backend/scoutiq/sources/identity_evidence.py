"""Parsers and fetchers for public NBA-id identity evidence (nba_api player index, Wikidata).

No database or settings dependency. The nba_api index is read with `ast` only; its source is
never imported or executed. Callers supply a `requests.Session` carrying the ScoutIQ User-Agent.
"""
from __future__ import annotations

import ast
from datetime import date, datetime, timezone
from typing import Any

NBA_INDEX_URL = "https://raw.githubusercontent.com/swar/nba_api/master/src/nba_api/stats/library/data.py"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIDATA_QUERY = (
    'SELECT ?nba ?dob ?itemLabel WHERE { ?item wdt:P3647 ?nba . OPTIONAL { ?item wdt:P569 ?dob } '
    'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }'
)
TIMEOUT_SECONDS = 60


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_nba_index(source_text: str) -> list[dict[str, Any]]:
    """Read the module-level `players` list literal from nba_api's static data.py."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        raise ValueError(f"nba_api index is not valid Python source: {exc}") from exc
    node = None
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "players" for target in statement.targets
        ):
            node = statement.value
    if node is None:
        raise ValueError("nba_api index has no module-level `players` assignment")
    try:
        rows = ast.literal_eval(node)
    except (ValueError, SyntaxError) as exc:
        raise ValueError("nba_api `players` is not a literal") from exc
    if not isinstance(rows, list) or not rows:
        raise ValueError("nba_api `players` is empty")
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if (
            not isinstance(row, (list, tuple)) or len(row) != 5
            or isinstance(row[0], bool) or not isinstance(row[0], int)
            or not isinstance(row[3], str) or not row[3].strip()
            or not isinstance(row[4], bool)
        ):
            raise ValueError(f"malformed nba_api player row: {row!r}")
        parsed.append({"nba_id": row[0], "full_name": row[3], "is_active": row[4]})
    return parsed


def _iso_date(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def parse_wikidata(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep Wikidata rows that carry a numeric NBA.com player id (property P3647)."""
    try:
        bindings = payload["results"]["bindings"]
    except (KeyError, TypeError) as exc:
        raise ValueError("wikidata response lacks results.bindings") from exc
    if not isinstance(bindings, list):
        raise ValueError("wikidata results.bindings is not a list")
    rows: list[dict[str, Any]] = []
    for binding in bindings:
        nba_value = str((binding.get("nba") or {}).get("value") or "")
        if not nba_value.isdigit():
            continue
        rows.append({
            "nba_id": int(nba_value),
            "dob": _iso_date((binding.get("dob") or {}).get("value")),
            "label": str((binding.get("itemLabel") or {}).get("value") or ""),
        })
    return rows


def fetch_nba_index(session) -> tuple[str, dict[str, Any]]:
    response = session.get(NBA_INDEX_URL, timeout=TIMEOUT_SECONDS)
    if response.status_code != 200:
        raise RuntimeError(f"nba_api index fetch failed: HTTP {response.status_code}")
    return response.text, {"source_url": NBA_INDEX_URL, "fetched_at_utc": _utc_now()}


def fetch_wikidata(session) -> tuple[dict[str, Any], dict[str, Any]]:
    response = session.get(
        WIKIDATA_SPARQL_URL,
        params={"query": WIKIDATA_QUERY},
        headers={"Accept": "application/sparql-results+json"},
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise RuntimeError(f"wikidata fetch failed: HTTP {response.status_code}")
    return response.json(), {"source_url": WIKIDATA_SPARQL_URL, "fetched_at_utc": _utc_now()}
