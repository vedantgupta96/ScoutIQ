"""Read-only data-refresh coverage report: row counts, source mix and freshness per dataset.

Run before and after a refresh to see exactly what changed. Never writes to the database:
the connection starts with `SET TRANSACTION READ ONLY` and is rolled back at the end.

Usage:
    python -m scoutiq.etl.check_refresh_coverage
    python -m scoutiq.etl.check_refresh_coverage --json before.json
    python -m scoutiq.etl.check_refresh_coverage --compare before.json
    python -m scoutiq.etl.check_refresh_coverage --snapshot-dir snapshots/pre-refresh \\
        --snapshot-season 2025-26 --snapshot-season 2026-27
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from scoutiq.api.season import LATEST_SEASON, next_season
from scoutiq.config import settings

NOT_ON_ROSTER_PATTERN = "%:not_on_roster"


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _scalar(conn, sql: str, params: tuple | None = None):
    return conn.exec_driver_sql(sql, params).scalar()


def _rows(conn, sql: str, params: tuple | None = None) -> list:
    return conn.exec_driver_sql(sql, params).all()


def collect(conn) -> dict:
    """Gather every coverage number with read-only SQL."""
    ps_rows = _scalar(conn, "SELECT count(*) FROM player_seasons")
    ps_bpm = _scalar(conn, "SELECT count(*) FROM player_seasons WHERE advanced ? 'BPM'")
    by_season: dict[str, dict] = {}
    for season, rows, bpm, vorp, ws, usg, null_team in _rows(
        conn,
        "SELECT season, count(*),"
        " count(*) FILTER (WHERE advanced ? 'BPM'),"
        " count(*) FILTER (WHERE advanced ? 'VORP'),"
        " count(*) FILTER (WHERE advanced ? 'WS'),"
        " count(*) FILTER (WHERE advanced ? 'USG_PCT'),"
        " count(*) FILTER (WHERE team_id IS NULL)"
        " FROM player_seasons GROUP BY season ORDER BY season",
    ):
        by_season[season] = {
            "rows": rows,
            "with_bbref_bpm": bpm,
            "with_bbref_vorp": vorp,
            "with_bbref_ws": ws,
            "with_nba_usg_pct": usg,
            "null_team": null_team,
            "by_source": {},
            "newest_source_fetched_at": None,
        }
    for season, source, n, newest in _rows(
        conn,
        "SELECT season, source, count(*), max(source_fetched_at)"
        " FROM player_seasons GROUP BY season, source ORDER BY season, source",
    ):
        entry = by_season[season]
        entry["by_source"][source or "unstamped"] = n
        if newest is not None and (
            entry["newest_source_fetched_at"] is None or _iso(newest) > entry["newest_source_fetched_at"]
        ):
            entry["newest_source_fetched_at"] = _iso(newest)

    salary_by_season: dict[str, dict] = {}
    for season, source, n in _rows(
        conn,
        "SELECT season, source, count(*) FROM player_salaries GROUP BY season, source ORDER BY season, source",
    ):
        entry = salary_by_season.setdefault(season, {"rows": 0, "by_source": {}})
        entry["rows"] += n
        entry["by_source"][source] = n

    external_id_by_source = {
        source: n
        for source, n in _rows(
            conn, "SELECT source, count(*) FROM player_external_ids GROUP BY source ORDER BY source"
        )
    }

    team_counts = [
        n for (n,) in _rows(
            conn,
            "SELECT count(*) FROM players WHERE current_team_id IS NOT NULL GROUP BY current_team_id",
        )
    ]
    roster_times = _rows(conn, "SELECT min(current_team_updated_at), max(current_team_updated_at) FROM players")[0]
    cap_rows = _rows(
        conn,
        "SELECT season, salary_cap, tax_line, first_apron, second_apron"
        " FROM cap_constants ORDER BY season",
    )
    latest_cap = cap_rows[-1] if cap_rows else None
    contract_row = _rows(conn, "SELECT count(*), max(scraped_at) FROM contracts")[0]

    return {
        "baseline": {
            "valuation_baseline_season": LATEST_SEASON,
            "etl_current_season": settings.CURRENT_SEASON,
            "last_configured_season": settings.seasons[-1],
        },
        "player_seasons": {
            "rows": ps_rows,
            "with_bbref_bpm": ps_bpm,
            "by_season": by_season,
            "seasons_beyond_baseline": [s for s in by_season if s > LATEST_SEASON],
        },
        "external_ids": {"by_source": external_id_by_source},
        "player_salaries": {
            "rows": _scalar(conn, "SELECT count(*) FROM player_salaries"),
            "by_season": salary_by_season,
        },
        "rosters": {
            "players": _scalar(conn, "SELECT count(*) FROM players"),
            "assigned": _scalar(conn, "SELECT count(*) FROM players WHERE current_team_id IS NOT NULL"),
            "teams_with_players": len(team_counts),
            "min_per_team": min(team_counts) if team_counts else None,
            "max_per_team": max(team_counts) if team_counts else None,
            "not_on_roster_marked": _scalar(
                conn,
                "SELECT count(*) FROM players WHERE current_team_id IS NULL AND current_team_source LIKE %s",
                (NOT_ON_ROSTER_PATTERN,),
            ),
            "by_source": {
                source: n
                for source, n in _rows(
                    conn,
                    "SELECT current_team_source, count(*) FROM players"
                    " WHERE current_team_source IS NOT NULL GROUP BY current_team_source"
                    " ORDER BY current_team_source",
                )
            },
            "oldest_update": _iso(roster_times[0]),
            "newest_update": _iso(roster_times[1]),
        },
        "cap_constants": {
            "seasons": len(cap_rows),
            "latest_season": latest_cap[0] if latest_cap else None,
            "latest_season_complete": bool(latest_cap) and all(v is not None for v in latest_cap[1:]),
        },
        "contracts": {
            "rows": contract_row[0],
            "latest_scraped_at": _iso(contract_row[1]),
            "latest_contract_year_season": _scalar(conn, "SELECT max(season) FROM contract_years"),
        },
        "player_valuations": {
            "rows": _scalar(conn, "SELECT count(*) FROM player_valuations"),
            "by_season": {
                season: n
                for season, n in _rows(
                    conn, "SELECT season, count(*) FROM player_valuations GROUP BY season ORDER BY season"
                )
            },
            "latest_computed_at": _iso(_scalar(conn, "SELECT max(computed_at) FROM player_valuations")),
        },
    }


def cache_summary(raw_dir: Path) -> dict:
    """File count, bytes and mtime span of the raw scrape cache (recursive); zeros if missing."""
    raw_dir = Path(raw_dir)
    files = [p for p in raw_dir.rglob("*") if p.is_file()] if raw_dir.is_dir() else []
    stats = [p.stat() for p in files]
    mtimes = [st.st_mtime for st in stats]
    return {
        "dir": str(raw_dir),
        "files": len(files),
        "bytes": sum(st.st_size for st in stats),
        "oldest_mtime": datetime.fromtimestamp(min(mtimes), tz=timezone.utc).isoformat() if mtimes else None,
        "newest_mtime": datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat() if mtimes else None,
    }


def flatten(report: dict, prefix: str = "") -> dict[str, object]:
    """Dotted-path -> leaf value for every leaf in a nested report."""
    out: dict[str, object] = {}
    for key, value in report.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(flatten(value, path))
        else:
            out[path] = value
    return out


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def diff_reports(before: dict, after: dict) -> list[dict]:
    """One entry per leaf that differs between two reports (generated_at is ignored)."""
    flat_before = flatten({k: v for k, v in before.items() if k != "generated_at"})
    flat_after = flatten({k: v for k, v in after.items() if k != "generated_at"})
    out = []
    for path in sorted(set(flat_before) | set(flat_after)):
        b, a = flat_before.get(path), flat_after.get(path)
        if path in flat_before and path in flat_after and b == a:
            continue
        out.append({
            "path": path,
            "before": b,
            "after": a,
            "delta": a - b if _is_number(a) and _is_number(b) else None,
        })
    return out


def render_text(report: dict) -> str:
    flat = flatten(report)
    return "\n".join(f"{path}: {value}" for path, value in flat.items())


def render_diff(diff: list[dict]) -> str:
    if not diff:
        return "no differences"
    lines = []
    for entry in diff:
        delta = f" ({entry['delta']:+g})" if entry["delta"] is not None else ""
        lines.append(f"{entry['path']}: {entry['before']} -> {entry['after']}{delta}")
    return "\n".join(lines)


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def _dump(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, default=_json_default, sort_keys=True) + "\n")


def _table_rows(conn, sql: str, params: tuple | None = None) -> list[dict]:
    return [dict(r._mapping) for r in conn.exec_driver_sql(sql, params).all()]


def write_snapshot(conn, snapshot_dir: Path, seasons: list[str], report: dict) -> list[Path]:
    """Write the report plus raw per-season rows to `snapshot_dir`; refuses a non-empty dir."""
    snapshot_dir = Path(snapshot_dir)
    if snapshot_dir.exists() and any(snapshot_dir.iterdir()):
        raise FileExistsError(f"snapshot dir {snapshot_dir} already exists and is not empty")
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    def emit(name: str, payload) -> None:
        path = snapshot_dir / name
        _dump(path, payload)
        written.append(path)

    emit("coverage.json", report)
    emit(
        "players_current_team.json",
        _table_rows(
            conn,
            "SELECT player_id, full_name, current_team_id, current_team_source,"
            " current_team_updated_at, is_two_way FROM players"
            " WHERE current_team_id IS NOT NULL OR current_team_source IS NOT NULL"
            " ORDER BY player_id",
        ),
    )
    for season in seasons:
        emit(
            f"player_seasons_{season}.json",
            _table_rows(conn, "SELECT * FROM player_seasons WHERE season = %s ORDER BY player_id", (season,)),
        )
        emit(
            f"player_salaries_{season}.json",
            _table_rows(conn, "SELECT * FROM player_salaries WHERE season = %s ORDER BY player_id, id", (season,)),
        )
    return written


def _connect():
    from scoutiq.db import engine

    if engine is None:
        raise RuntimeError("No DB engine — set DATABASE_URL in backend/.env first.")
    return engine.connect()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only data-refresh coverage report.")
    parser.add_argument("--json", metavar="PATH", default=None, help="write the report as JSON")
    parser.add_argument("--snapshot-dir", metavar="DIR", default=None, help="also dump raw rows here (must be empty/new)")
    parser.add_argument(
        "--snapshot-season", action="append", dest="snapshot_seasons", metavar="YYYY-YY",
        help="Season to snapshot (repeatable). Default: the baseline season and the one after it.",
    )
    parser.add_argument("--compare", metavar="BEFORE.json", default=None, help="print the diff vs a saved report")
    parser.add_argument("--raw-dir", default=str(settings.RAW_DIR), help="raw scrape cache directory")
    args = parser.parse_args(argv)

    snapshot_seasons = args.snapshot_seasons or [LATEST_SEASON, next_season(LATEST_SEASON)]

    conn = _connect()
    try:
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        report = collect(conn)
        report["raw_cache"] = cache_summary(Path(args.raw_dir))
        report["generated_at"] = datetime.now(tz=timezone.utc).isoformat()
        if args.snapshot_dir:
            for path in write_snapshot(conn, Path(args.snapshot_dir), snapshot_seasons, report):
                print(f"snapshot: {path}")
    finally:
        conn.rollback()
        conn.close()

    print(render_text(report))
    if args.json:
        _dump(Path(args.json), report)
    if args.compare:
        before = json.loads(Path(args.compare).read_text())
        print("\n-- diff vs " + args.compare)
        print(render_diff(diff_reports(before, report)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
