"""Small, source-native parser for ESPN's public NBA roster and season-total APIs.

This adapter deliberately returns dictionaries suitable for an audit cache.  It has no
database, settings, or model dependency: a later reviewed loader may decide how (or
whether) to attribute these provider records to ScoutIQ players.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlparse

from scoutiq.sources import nba

ESPN_SITE_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_CORE_BASE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
ESPN_TEAM_ALIASES = {"NY": "NYK", "GS": "GSW", "NO": "NOP", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}
BOX_NAME_MAP = {
    "points": "PTS", "totalRebounds": "REB", "offensiveRebounds": "OREB",
    "defensiveRebounds": "DREB", "assists": "AST", "steals": "STL", "blocks": "BLK",
    "turnovers": "TOV", "fouls": "PF", "gamesStarted": "GS",
    "fieldGoalsMade": "FGM", "fieldGoalsAttempted": "FGA",
    "threePointFieldGoalsMade": "FG3M", "threePointFieldGoalsAttempted": "FG3A",
    "freeThrowsMade": "FTM", "freeThrowsAttempted": "FTA",
}
PERCENT_NAME_MAP = {
    "fieldGoalPct": "FG_PCT", "threePointFieldGoalPct": "FG3_PCT", "freeThrowPct": "FT_PCT",
}
REQUIRED_STAT_NAMES = frozenset(BOX_NAME_MAP) | frozenset(PERCENT_NAME_MAP)


class ESPNValidationError(ValueError):
    """A public response did not establish the claimed roster or stat fact."""


@dataclass(frozen=True)
class ESPNTeam:
    provider_id: int
    abbreviation: str
    scoutiq_team_id: int
    name: str


def season_year(season: str) -> int:
    match = re.fullmatch(r"(\d{4})-(\d{2})", season)
    if not match:
        raise ESPNValidationError(f"season must look like 2026-27, got {season!r}")
    start, suffix = int(match.group(1)), int(match.group(2))
    if suffix != (start + 1) % 100:
        raise ESPNValidationError(f"season end year must follow start year, got {season!r}")
    return start + 1


def normalize_name(value: str) -> str:
    """Casefold names for an exact normalized-name plus DOB identity check."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def dob_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError as exc:
        raise ESPNValidationError(f"invalid dateOfBirth {value!r}") from exc


def validate_teams(payload: dict[str, Any]) -> list[ESPNTeam]:
    try:
        rows = payload["sports"][0]["leagues"][0]["teams"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ESPNValidationError("teams payload lacks sports[0].leagues[0].teams") from exc
    known = {row["abbreviation"]: row["team_id"] for row in nba.team_rows()}
    teams: list[ESPNTeam] = []
    seen_provider: set[int] = set()
    seen_abbreviations: set[str] = set()
    for wrapper in rows:
        team = wrapper.get("team", {})
        raw_abbr = str(team.get("abbreviation") or "").upper()
        abbreviation = ESPN_TEAM_ALIASES.get(raw_abbr, raw_abbr)
        try:
            provider_id = int(team["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ESPNValidationError(f"team has invalid provider id: {team!r}") from exc
        if abbreviation not in known:
            raise ESPNValidationError(f"unknown ESPN team abbreviation {raw_abbr!r}")
        if provider_id in seen_provider or abbreviation in seen_abbreviations:
            raise ESPNValidationError(f"duplicate ESPN team {provider_id}/{abbreviation}")
        seen_provider.add(provider_id)
        seen_abbreviations.add(abbreviation)
        teams.append(ESPNTeam(provider_id, abbreviation, known[abbreviation], str(team.get("displayName") or abbreviation)))
    if len(teams) != 30 or len(seen_abbreviations) != 30:
        raise ESPNValidationError(f"expected 30 distinct known NBA teams, got {len(teams)}")
    return sorted(teams, key=lambda row: row.provider_id)


def validate_roster(payload: dict[str, Any], team: ESPNTeam, season: str) -> list[dict[str, Any]]:
    year = season_year(season)
    response_season = payload.get("season", {})
    if (response_season.get("year"), response_season.get("displayName"), response_season.get("type")) != (year, season, 2):
        raise ESPNValidationError(f"roster {team.abbreviation} has wrong season metadata")
    response_team = payload.get("team")
    if not isinstance(response_team, dict) or str(response_team.get("id")) != str(team.provider_id):
        raise ESPNValidationError(f"roster team identity disagrees for {team.abbreviation}")
    athletes = payload.get("athletes")
    if not isinstance(athletes, list) or not 12 <= len(athletes) <= 23:
        raise ESPNValidationError(f"{team.abbreviation} roster count must be 12..23")
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for athlete in athletes:
        try:
            provider_id = int(athlete["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ESPNValidationError(f"{team.abbreviation} athlete has invalid id") from exc
        full_name = str(athlete.get("fullName") or "").strip()
        if not full_name or provider_id in seen:
            raise ESPNValidationError(f"{team.abbreviation} has blank or duplicate athlete identity")
        seen.add(provider_id)
        rows.append({
            "provider_id": provider_id,
            "full_name": full_name,
            "date_of_birth": dob_date(athlete.get("dateOfBirth")),
            "current_team_abbreviation": team.abbreviation,
            "current_team_provider_id": team.provider_id,
            "scoutiq_team_id": team.scoutiq_team_id,
            "salary_context": athlete.get("contract") or athlete.get("salary"),
        })
    return rows


def _numeric(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ESPNValidationError(f"stat {name} has no exact numeric value")
    return float(value)


def _stat_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the explicit total split only; never calculate totals from display averages."""
    splits = payload.get("splits")
    if isinstance(splits, dict) and splits.get("id") == "0" and splits.get("type") == "total":
        categories = splits.get("categories")
        if isinstance(categories, list):
            return [stat for category in categories for stat in category.get("stats", []) if isinstance(stat, dict)]
        if isinstance(splits.get("stats"), list):
            return [stat for stat in splits["stats"] if isinstance(stat, dict)]
    raise ESPNValidationError("statistics payload lacks an explicit total split")


def parse_season_totals(payload: dict[str, Any], athlete_id: int, season: str) -> dict[str, Any]:
    """Validate a core stat response and map only exact box-score values."""
    year = season_year(season)
    reference = str(payload.get("$ref") or "")
    expected = f"seasons/{year}/types/2/athletes/{athlete_id}/statistics/0"
    if urlparse(reference).path != f"/v2/sports/basketball/leagues/nba/{expected}":
        raise ESPNValidationError("statistics $ref does not identify requested athlete, season, and total type")
    season_ref = str((payload.get("season") or {}).get("$ref") or "")
    athlete_ref = str((payload.get("athlete") or {}).get("$ref") or "")
    if not urlparse(season_ref).path.endswith(f"/seasons/{year}"):
        raise ESPNValidationError("statistics season $ref does not identify requested season")
    if not urlparse(athlete_ref).path.endswith(f"/seasons/{year}/athletes/{athlete_id}"):
        raise ESPNValidationError("statistics athlete $ref does not identify requested athlete")
    entries = _stat_entries(payload)
    names = [str(entry.get("name")) for entry in entries]
    if len(names) != len(set(names)):
        raise ESPNValidationError("statistics total contains duplicate stat names")
    values = {str(entry.get("name")): entry.get("value") for entry in entries}
    if "gamesPlayed" not in values or "minutes" not in values:
        raise ESPNValidationError("statistics total lacks gamesPlayed or minutes")
    gp = _numeric(values["gamesPlayed"], "gamesPlayed")
    minutes = _numeric(values["minutes"], "minutes")
    if not gp.is_integer() or gp < 0 or minutes < 0:
        raise ESPNValidationError("gamesPlayed/minutes have invalid units")
    missing = REQUIRED_STAT_NAMES - values.keys()
    if missing:
        raise ESPNValidationError(f"statistics total lacks expected box-score fields: {sorted(missing)}")
    box = {key: _numeric(values[name], name) for name, key in BOX_NAME_MAP.items()}
    for name, key in BOX_NAME_MAP.items():
        if box[key] < 0 or not box[key].is_integer():
            raise ESPNValidationError(f"count stat {name} has invalid units")
    for name, key in PERCENT_NAME_MAP.items():
        value = _numeric(values[name], name)
        if not 0 <= value <= 100:
            raise ESPNValidationError(f"percentage {name} is not percentage points")
        box[key] = value / 100
    if gp == 0 and (minutes != 0 or any(value != 0 for value in box.values())):
        raise ESPNValidationError("zero games played conflicts with positive production")
    if box["PTS"] != 2 * box["FGM"] + box["FG3M"] + box["FTM"]:
        raise ESPNValidationError("points do not reconcile with made shots and free throws")
    if box["REB"] != box["OREB"] + box["DREB"]:
        raise ESPNValidationError("rebounds do not reconcile with offensive and defensive rebounds")
    return {"provider_id": athlete_id, "season": season, "gp": int(gp), "minutes": minutes, "box": box}
