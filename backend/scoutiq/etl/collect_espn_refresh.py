"""Cache ESPN's current NBA roster and regular-season-total refresh artifacts.

This is a source proof, not a database loader.  It writes raw responses, validated
normalizations, and a manifest under --output-dir; every artifact remains attributable to
the roster snapshot, which necessarily excludes players already waived or off roster.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from scoutiq.sources import espn

USER_AGENT = "ScoutIQ/1.0 (+https://github.com/vedantgupta96/ScoutIQ)"
TIMEOUT_SECONDS = 15
PAUSE_SECONDS = 0.3


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class ESPNClient:
    """Polite sequential HTTP client with one retry only for transient failures."""

    def __init__(self, session: requests.Session | None = None, pause: float = PAUSE_SECONDS):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.pause = max(pause, PAUSE_SECONDS)
        self._last_request = 0.0

    def get_json(self, url: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        for attempt in (1, 2):
            wait = self.pause - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.session.get(url, timeout=TIMEOUT_SECONDS)
                self._last_request = time.monotonic()
            except requests.Timeout as exc:
                if attempt == 1:
                    continue
                return None, {"url": url, "attempts": attempt, "error": type(exc).__name__}
            except requests.RequestException as exc:
                if attempt == 1:
                    continue
                return None, {"url": url, "attempts": attempt, "error": type(exc).__name__}
            metadata = {"url": url, "attempts": attempt, "status": response.status_code, "fetched_at_utc": _utc_now()}
            if response.status_code in (403, 429):
                return None, {**metadata, "error": f"HTTP {response.status_code}", "halt": True}
            if 500 <= response.status_code < 600 and attempt == 1:
                continue
            if response.status_code != 200:
                return None, {**metadata, "error": f"HTTP {response.status_code}"}
            try:
                return response.json(), metadata
            except ValueError:
                return None, {**metadata, "error": "invalid JSON"}
        raise AssertionError("unreachable")


def _write_response(path: Path, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
    """Persist a raw payload and its source provenance in one atomic file replacement."""
    _write_json(path, {"source_url": metadata["url"], "fetched_at_utc": metadata["fetched_at_utc"], "payload": payload})


def _cached_valid(path: Path, validator, *args):
    """Return (missing|valid|invalid, parsed response); invalid evidence is never refreshed."""
    if not path.exists():
        return "missing", None
    try:
        envelope = _read_json(path)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
            raise ValueError("response cache lacks payload envelope")
        if not isinstance(envelope.get("source_url"), str) or not isinstance(envelope.get("fetched_at_utc"), str):
            raise ValueError("response cache lacks provenance")
        return "valid", (envelope["payload"], validator(envelope["payload"], *args),
                         {"url": envelope["source_url"], "fetched_at_utc": envelope["fetched_at_utc"]})
    except (OSError, ValueError, espn.ESPNValidationError):
        return "invalid", None


def reconcile_identity(roster: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Exact normalized name plus DOB reconciliation; it never manufactures player IDs."""
    indexed: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in evidence:
        if not row.get("verified") or not row.get("dob") or not row.get("name"):
            continue
        indexed.setdefault((espn.normalize_name(str(row["name"])), str(row["dob"])), []).append(row)
    matched, unmatched, ambiguous = [], [], []
    assigned_nba_ids: set[int] = set()
    for athlete in roster:
        dob = athlete.get("date_of_birth")
        key = (espn.normalize_name(athlete["full_name"]), dob) if dob else None
        candidates = indexed.get(key, []) if key else []
        record = {"provider_id": athlete["provider_id"], "full_name": athlete["full_name"], "date_of_birth": dob}
        if len(candidates) == 1:
            candidate = candidates[0]
            nba_id = candidate.get("nba_id")
            if isinstance(nba_id, bool) or not isinstance(nba_id, int) or nba_id <= 0:
                raise ValueError("verified identity evidence has an invalid nba_id")
            if nba_id in assigned_nba_ids:
                ambiguous.append({**record, "candidate_nba_ids": [nba_id], "reason": "NBA id already assigned"})
                continue
            assigned_nba_ids.add(nba_id)
            matched.append({**record, "nba_id": nba_id, "evidence_name": candidate["name"],
                            "evidence_dob": candidate["dob"], "bbref_slug": candidate.get("bbref_slug")})
        elif candidates:
            ambiguous.append({**record, "candidate_nba_ids": [row["nba_id"] for row in candidates]})
        else:
            unmatched.append(record)
    return {"matched": matched, "unmatched": unmatched, "ambiguous": ambiguous,
            "counts": {"matched": len(matched), "unmatched": len(unmatched), "ambiguous": len(ambiguous)}}


def collect(season: str, output_dir: Path, *, rosters_only: bool = False,
            client: ESPNClient | None = None, identity_evidence: Path | None = None) -> dict[str, Any]:
    """Fetch or resume a season-native source cache. Failed stats remain explicit in manifest."""
    output_dir = Path(output_dir)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        previous = _read_json(manifest_path)
        if previous.get("season") != season:
            raise ValueError(f"output directory belongs to {previous.get('season')!r}, not {season!r}")
        cache = dict(previous.get("cache", {}))
    else:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ValueError("output directory is nonempty and has no ScoutIQ ESPN manifest")
        cache = {}
    if identity_evidence is not None and not identity_evidence.is_file():
        raise ValueError(f"identity evidence does not exist: {identity_evidence}")
    client = client or ESPNClient()
    manifest: dict[str, Any] = {"season": season, "season_year": espn.season_year(season), "generated_at_utc": _utc_now(),
                                "source": "ESPN public APIs", "coverage_note": "roster-based; waived/off-roster players are absent",
                                "requests": [], "errors": [], "missing_stats": [], "none_played": [], "cache": cache}
    # Claim the output directory before the first response write. If the process dies after
    # writing an envelope but before the next manifest update, resume still recognizes this
    # directory and recovers the response's own provenance.
    _write_json(manifest_path, manifest)
    teams_url = f"{espn.ESPN_SITE_BASE}/teams"
    teams_path = output_dir / "raw" / "teams.json"
    cache_state, cached = _cached_valid(teams_path, espn.validate_teams)
    if cache_state == "valid":
        _, teams, metadata = cached
        manifest["requests"].append({"source": "cache", **metadata})
    elif cache_state == "invalid":
        manifest["errors"].append({"kind": "teams_cache_validation", "error": "invalid raw response was preserved"})
        _write_json(manifest_path, manifest)
        return manifest
    else:
        payload, metadata = client.get_json(teams_url)
        manifest["requests"].append(metadata)
        if payload is None:
            manifest["errors"].append({"kind": "teams", **metadata})
            _write_json(manifest_path, manifest)
            return manifest
        _write_response(teams_path, payload, metadata)
        cache["teams"] = metadata
        _write_json(manifest_path, manifest)
        try:
            teams = espn.validate_teams(payload)
        except espn.ESPNValidationError as exc:
            manifest["errors"].append({"kind": "teams_validation", "error": str(exc)})
            _write_json(manifest_path, manifest)
            return manifest
    roster_rows: list[dict[str, Any]] = []
    seen_athletes: set[int] = set()
    validated_roster_teams = 0
    for team in teams:
        url = f"{espn.ESPN_SITE_BASE}/teams/{team.provider_id}/roster?season={espn.season_year(season)}"
        path = output_dir / "raw" / "rosters" / f"{team.provider_id}.json"
        cache_state, cached = _cached_valid(path, espn.validate_roster, team, season)
        if cache_state == "valid":
            _, rows, metadata = cached
            manifest["requests"].append({"source": "cache", **metadata})
        elif cache_state == "invalid":
            manifest["errors"].append({"kind": "roster_cache_validation", "team": team.abbreviation, "error": "invalid raw response was preserved"})
            _write_json(manifest_path, manifest)
            return manifest
        else:
            payload, metadata = client.get_json(url)
            manifest["requests"].append(metadata)
            if payload is None:
                manifest["errors"].append({"kind": "roster", "team": team.abbreviation, **metadata})
                if metadata.get("halt"):
                    _write_json(manifest_path, manifest)
                    return manifest
                continue
            _write_response(path, payload, metadata)
            cache[f"roster:{team.provider_id}"] = metadata
            _write_json(manifest_path, manifest)
            try:
                rows = espn.validate_roster(payload, team, season)
            except espn.ESPNValidationError as exc:
                manifest["errors"].append({"kind": "roster_validation", "team": team.abbreviation, "error": str(exc)})
                continue
        validated_roster_teams += 1
        for row in rows:
            if row["provider_id"] in seen_athletes:
                manifest["errors"].append({"kind": "duplicate_athlete", "provider_id": row["provider_id"]})
            else:
                seen_athletes.add(row["provider_id"])
                roster_rows.append(row)
    _write_json(output_dir / "normalized_roster.json", roster_rows)
    if identity_evidence:
        _write_json(output_dir / "identity_report.json", reconcile_identity(roster_rows, _read_json(identity_evidence)))
    if not rosters_only:
        for athlete in roster_rows:
            athlete_id = athlete["provider_id"]
            url = f"{espn.ESPN_CORE_BASE}/seasons/{espn.season_year(season)}/types/2/athletes/{athlete_id}/statistics/0"
            path = output_dir / "raw" / "stats" / f"{athlete_id}.json"
            cache_state, cached = _cached_valid(path, espn.parse_season_totals, athlete_id, season)
            if cache_state == "valid":
                _, parsed, metadata = cached
                manifest["requests"].append({"source": "cache", **metadata})
            elif cache_state == "invalid":
                manifest["errors"].append({"kind": "stats_cache_validation", "provider_id": athlete_id, "error": "invalid raw response was preserved"})
                _write_json(manifest_path, manifest)
                return manifest
            else:
                payload, metadata = client.get_json(url)
                manifest["requests"].append(metadata)
                if payload is None:
                    destination = manifest["missing_stats"] if metadata.get("status") == 404 else manifest["errors"]
                    destination.append({"kind": "stats", "provider_id": athlete_id, **metadata})
                    if metadata.get("halt"):
                        _write_json(manifest_path, manifest)
                        return manifest
                    continue
                _write_response(path, payload, metadata)
                cache[f"stats:{athlete_id}"] = metadata
                _write_json(manifest_path, manifest)
                try:
                    parsed = espn.parse_season_totals(payload, athlete_id, season)
                except espn.ESPNValidationError as exc:
                    manifest["errors"].append({"kind": "stats_validation", "provider_id": athlete_id, "error": str(exc)})
                    continue
            if parsed["gp"] == 0:
                manifest["none_played"].append({"provider_id": athlete_id, "reason": "zero games played"})
                continue
            _write_json(output_dir / "normalized_stats" / f"{athlete_id}.json", parsed)
            manifest.setdefault("validated_stats", 0)
            manifest["validated_stats"] += 1
    manifest["counts"] = {"teams": len(teams), "validated_roster_teams": validated_roster_teams,
                          "roster_athletes": len(roster_rows), "validated_stats": manifest.get("validated_stats", 0),
                          "errors": len(manifest["errors"]), "missing_stats": len(manifest["missing_stats"]), "none_played": len(manifest["none_played"])}
    _write_json(manifest_path, manifest)
    return manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cache a validated ESPN NBA roster/stat snapshot; never writes the database.")
    parser.add_argument("--season", default="2026-27", help="season display name, e.g. 2026-27")
    parser.add_argument("--output-dir", type=Path, required=True, help="new season-specific source-native artifact directory")
    parser.add_argument("--rosters-only", action="store_true", help="skip player season-total requests")
    parser.add_argument("--identity-evidence", type=Path, help="optional verified name+DOB evidence JSON; writes candidates only")
    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    result = collect(args.season, args.output_dir, rosters_only=args.rosters_only,
                     identity_evidence=args.identity_evidence)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["errors"] or result.get("counts", {}).get("validated_roster_teams") != 30:
        raise SystemExit(1)
