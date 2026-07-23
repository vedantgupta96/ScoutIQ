"""Read-only coverage probe for the tracking/hustle spike (issue #94).

Reports, for each (family, season[, measure_type]):
  1. request outcome        — ok/failed, http status or exception type, attempts, cache vs live
  2. ID-based join rate      — fraction of returned rows whose numeric player id matches
                                players.player_id; join is ID-only, name matching is never used
  3. per-field null rate     — fraction of null/NaN values per candidate column

Reads from the DB (players.player_id) but never writes. Exits non-zero if any source
request fails, so a blocked/failing source is a visible, scriptable failure.

Usage:
    python -m scoutiq.etl.check_tracking_coverage --season 2024-25 --season 2023-24 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from scoutiq.db import get_session
from scoutiq.sources.nba_tracking import (
    iter_probe_targets,
    FAMILY_REGISTRY,
    TRACKING_MEASURE_TYPES,
    fetch_family,
    player_id_field,
)

DEFAULT_SEASONS = ["2024-25", "2023-24"]
UNMATCHED_PRINT_CAP = 20


def _known_player_ids(session) -> set[int]:
    rows = session.execute(text("SELECT player_id FROM players")).all()
    return {row[0] for row in rows}


def join_rate(frame: pd.DataFrame, id_field: str, known_ids: set[int]) -> dict:
    """ID presence and join success are reported as SEPARATE facts.

    Dividing matches by only the rows that carry an id overstates coverage — a
    sample of one matching id plus one null id would read as a 100% join rate
    while printing 1/2. `join_rate` is therefore computed over ALL sampled rows,
    with the id-present subset reported alongside rather than hidden in the
    denominator.
    """
    total = len(frame)
    if id_field not in frame.columns or frame.empty:
        return {
            "total_rows": total,
            "id_field_present": id_field in frame.columns,
            "rows_with_id": 0,
            "rows_missing_id": total,
            "id_presence_rate": 0.0,
            "matched": 0,
            "join_rate": 0.0,
            "match_rate_where_id_present": None,
            "unmatched_ids": [],
            "unmatched_count": 0,
        }
    ids = frame[id_field].dropna().astype(int).tolist()
    matched = [pid for pid in ids if pid in known_ids]
    unmatched = sorted({pid for pid in ids if pid not in known_ids})
    return {
        "total_rows": total,
        "id_field_present": True,
        "rows_with_id": len(ids),
        "rows_missing_id": total - len(ids),
        "id_presence_rate": (len(ids) / total) if total else 0.0,
        "matched": len(matched),
        # Denominator is every sampled row, not just those carrying an id.
        "join_rate": (len(matched) / total) if total else 0.0,
        "match_rate_where_id_present": (len(matched) / len(ids)) if ids else None,
        "unmatched_ids": unmatched[:UNMATCHED_PRINT_CAP],
        "unmatched_count": len(unmatched),
    }


MINUTES_COLUMNS = ("MIN", "MINUTES", "MIN_TOTAL")


def qualified_sample(frame: pd.DataFrame, sample_size: int | None, min_minutes: float) -> tuple[pd.DataFrame, dict]:
    """Rotation-player sample, not raw endpoint ordering.

    `frame.head(N)` samples whatever order the endpoint happened to return, which
    is not a representative rotation-player set. Where a minutes column exists we
    qualify on `min_minutes` and take the highest-minutes rows; where it does not,
    we fall back to head() and say so, so the report never implies a qualified
    sample it did not take.
    """
    minutes_col = next((c for c in MINUTES_COLUMNS if c in frame.columns), None)
    meta = {
        "sample_size_requested": sample_size,
        "min_minutes": min_minutes,
        "minutes_column": minutes_col,
        "qualified": minutes_col is not None,
        "rows_before_qualification": len(frame),
    }
    if minutes_col is None:
        meta["note"] = (
            "No minutes column found; sample is raw endpoint order (NOT a qualified "
            "rotation-player sample). Treat any rate from it as unrepresentative."
        )
        sample = frame.head(sample_size) if sample_size else frame
    else:
        qualified = frame[pd.to_numeric(frame[minutes_col], errors="coerce").fillna(0) >= min_minutes]
        qualified = qualified.sort_values(minutes_col, ascending=False)
        sample = qualified.head(sample_size) if sample_size else qualified
    meta["rows_after_qualification"] = len(sample)
    return sample, meta


def null_rates(frame: pd.DataFrame, sample_size: int | None = None) -> dict:
    sample = frame.head(sample_size) if sample_size else frame
    if sample.empty:
        return {}
    return {col: float(sample[col].isna().mean()) for col in sample.columns}


def _print_outcome(outcome) -> None:
    status = "OK" if outcome.ok else "FAILED"
    label = outcome.measure_type or ""
    print(
        f"[{status}] family={outcome.family} season={outcome.season} measure_type={label} "
        f"source={outcome.source} rows={outcome.rows} attempts={outcome.attempts} "
        f"elapsed_s={outcome.elapsed_s:.2f} http_status={outcome.http_status} "
        f"error={outcome.error_type}: {outcome.error_message}"
    )


def run(args: argparse.Namespace) -> dict:
    seasons = args.season or DEFAULT_SEASONS
    measure_types = args.measure_types.split(",") if args.measure_types else TRACKING_MEASURE_TYPES

    with get_session() as session:
        known_ids = _known_player_ids(session)

    results: list[dict] = []
    any_failure = False

    # Single iteration path — iter_probe_targets() owns family/season/measure
    # expansion so the CLI and the helper cannot drift apart.
    for family, season, measure_type in iter_probe_targets(seasons, measure_types):
        outcome = fetch_family(
            family,
            season,
            measure_type=measure_type,
            use_cache=not args.no_cache,
            cache_dir=Path(args.cache_dir) if args.cache_dir else None,
            pause=args.pause,
            timeout=args.timeout,
        )
        _print_outcome(outcome)

        entry: dict = {
            "family": family,
            "season": season,
            "measure_type": measure_type,
            "ok": outcome.ok,
            "source": outcome.source,
            "http_status": outcome.http_status,
            "error_type": outcome.error_type,
            "error_message": outcome.error_message,
            "attempts": outcome.attempts,
            "elapsed_s": outcome.elapsed_s,
            "fetched_at_utc": outcome.fetched_at_utc,
            "rows": outcome.rows,
        }

        if not outcome.ok:
            any_failure = True
            entry["join"] = None
            entry["null_rates"] = None
        else:
            frame = outcome.frame if outcome.frame is not None else pd.DataFrame()
            sample, sample_meta = qualified_sample(frame, args.sample_size, args.min_minutes)
            if not sample_meta["qualified"]:
                print(f"    WARNING: {sample_meta['note']}")
            id_field = player_id_field(family)
            join = join_rate(sample, id_field, known_ids)
            print(
                f"    join_rate={join['join_rate']:.2%} (matched {join['matched']}/"
                f"{join['total_rows']} sampled rows); id present on "
                f"{join['rows_with_id']}/{join['total_rows']} "
                f"({join['id_presence_rate']:.2%}); unmatched_count="
                f"{join.get('unmatched_count', 0)} unmatched_ids(sample)="
                f"{join['unmatched_ids']}"
            )
            nulls = null_rates(sample, args.sample_size)
            for col, rate in nulls.items():
                print(f"    null_rate[{col}] = {rate:.2%}")
            entry["join"] = join
            entry["null_rates"] = nulls
            entry["sample"] = sample_meta

        results.append(entry)

    summary = {"seasons": seasons, "results": results, "any_failure": any_failure}
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_tracking_coverage",
        description="Read-only probe: request outcome, ID join rate, and null rate for "
        "nba.com hustle/tracking/defense/shooting endpoints.",
    )
    parser.add_argument(
        "--season",
        action="append",
        default=None,
        help="Season to probe, e.g. 2024-25. Repeatable. Defaults to the two most recent seasons.",
    )
    parser.add_argument(
        "--measure-types",
        default=None,
        help="Comma list of PtMeasureType values for the tracking family "
        f"(default: {','.join(TRACKING_MEASURE_TYPES)}).",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="Cap the qualified sample at N rows (sampling, not a request-level limit).",
    )
    parser.add_argument(
        "--min-minutes",
        type=float,
        default=200.0,
        help="Minutes threshold qualifying a row as a rotation player before sampling "
        "(default: 200). If the frame has no minutes column the probe warns and falls "
        "back to raw endpoint order, which is NOT a representative sample.",
    )
    parser.add_argument("--cache-dir", default=None, help="Override the disk cache directory.")
    parser.add_argument("--no-cache", action="store_true", help="Bypass the disk cache (forces a live request).")
    parser.add_argument("--pause", type=float, default=1.5, help="Seconds to pace between live requests.")
    parser.add_argument("--timeout", type=int, default=45, help="Per-request timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Also emit a machine-readable JSON summary.")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    summary = run(args)
    sys.exit(1 if summary["any_failure"] else 0)


if __name__ == "__main__":
    main()
