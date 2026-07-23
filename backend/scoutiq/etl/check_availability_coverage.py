"""Reproducible read-only probe for the official NBA injury-report Availability Ledger
source spike (issue #95).

Reports, separately: (1) retrieval outcome per edition — ok / absent / failed; (2)
parsed row counts; (3) identity-match rates against `players`/`teams` (matched /
unmatched / ambiguous — never silently resolved); (4) which requested dates the
archive no longer serves. No DB writes. No risk/medical inference anywhere here —
`status` and `reason` are reported verbatim.

Usage:
    python -m scoutiq.etl.check_availability_coverage
    python -m scoutiq.etl.check_availability_coverage --date 2025-12-19 --editions 05PM,08PM --json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from scoutiq.db import get_session
from scoutiq.models import Player, Team
from scoutiq.sources.nba_injury_reports import (
    default_editions_for,
    DEFAULT_PAUSE,
    DEFAULT_TIMEOUT,
    AvailabilityRow,
    EditionOutcome,
    fetch_edition,
    normalize_name,
    parse_edition_text,
)

DEFAULT_DATES = ("2025-12-19", "2024-03-10", "2022-01-10")
DEFAULT_EDITIONS = ("05PM", "08PM")
EXAMPLE_CAP = 10

_ABSENT_CAVEAT = (
    "edition(s) classified absent — this is PROVISIONAL (S3 403 AccessDenied cannot "
    "distinguish 'never published' from 'access now restricted'). A sudden jump from "
    "mostly-ok to mostly-absent should be treated as a possible access change, not an "
    "archive fact."
)


@dataclass(frozen=True)
class IdentityMatch:
    row: AvailabilityRow
    player_match: str  # 'matched' | 'unmatched' | 'ambiguous'
    matched_player_id: int | None
    team_match: str  # 'matched' | 'unmatched'


def _reversed_name(player_name: str) -> str:
    if "," not in player_name:
        return player_name
    last, first = player_name.split(",", 1)
    return f"{first.strip()} {last.strip()}"


def _match_identities(
    rows: list[AvailabilityRow],
    players: list[tuple[int, str]],
    teams: list[str],
) -> list[IdentityMatch]:
    """`players` is (player_id, full_name) and `teams` is team names — plain values,
    not ORM instances, so matching cannot touch a closed session."""
    by_norm: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for pid, full_name in players:
        if full_name:
            by_norm[normalize_name(full_name)].append((pid, full_name))
    team_names = {normalize_name(name) for name in teams if name}

    out: list[IdentityMatch] = []
    for row in rows:
        norm = normalize_name(_reversed_name(row.player_name))
        candidates = by_norm.get(norm, [])
        if len(candidates) == 1:
            player_match, matched_id = "matched", candidates[0][0]
        elif len(candidates) > 1:
            player_match, matched_id = "ambiguous", None
        else:
            player_match, matched_id = "unmatched", None

        team_match = "matched" if row.team and normalize_name(row.team) in team_names else "unmatched"
        out.append(IdentityMatch(row=row, player_match=player_match, matched_player_id=matched_id, team_match=team_match))
    return out


def _is_indeterminate(outcomes: list[EditionOutcome]) -> bool:
    """True when a run produced zero usable ('ok') outcomes and at least one
    provisional-absent — absence dominating with no successes at all should read as
    a possible access-policy change to automation, not a quiet day (see the S3 review
    finding on issue #95). A run with at least one 'ok' and some scattered absents is
    not indeterminate; those are genuine per-edition absences."""
    ok_count = sum(1 for o in outcomes if o.status == "ok")
    absent_count = sum(1 for o in outcomes if o.status == "absent")
    return ok_count == 0 and absent_count > 0


def run(
    dates: list[str],
    editions: list[str],
    *,
    use_cache: bool = True,
    pause: float = DEFAULT_PAUSE,
    timeout: float = DEFAULT_TIMEOUT,
    as_json: bool = False,
    cache_dir: Path | None = None,
) -> int:
    # Materialise plain values inside the session. Carrying ORM instances out and
    # reading attributes later raises DetachedInstanceError once the session closes.
    with get_session() as session:
        players = [
            (pid, name)
            for pid, name in session.execute(select(Player.player_id, Player.full_name))
        ]
        teams = [name for (name,) in session.execute(select(Team.name))]

    outcomes: list[EditionOutcome] = []
    all_rows: list[AvailabilityRow] = []
    parse_summaries: dict[tuple[str, str], dict] = {}

    for date in dates:
        # None means "let the source pick per date" — the filename convention
        # changed on 2025-12-22, so a single fixed list makes one era look absent.
        date_editions = editions if editions else list(default_editions_for(date))
        for edition in date_editions:
            outcome = fetch_edition(
                date, edition, use_cache=use_cache, pause=pause, timeout=timeout, cache_dir=cache_dir
            )
            outcomes.append(outcome)
            if outcome.status == "ok" and outcome.raw_text:
                rows, summary = parse_edition_text(
                    outcome.raw_text,
                    edition_token_utc=outcome.edition_token_utc,
                    source_url=outcome.url,
                    pages=0,
                )
                all_rows.extend(rows)
                parse_summaries[(date, edition)] = {
                    "rows_parsed": summary.rows_parsed,
                    "unparseable_lines": summary.unparseable_lines,
                    "suspected_truncated_names": summary.suspected_truncated_names,
                }

    matches = _match_identities(all_rows, players, teams)
    player_counts = defaultdict(int)
    team_counts = defaultdict(int)
    for m in matches:
        player_counts[m.player_match] += 1
        team_counts[m.team_match] += 1

    absent_editions = [f"{o.date} {o.edition}" for o in outcomes if o.status == "absent"]
    failed_editions = [f"{o.date} {o.edition}" for o in outcomes if o.status == "failed"]
    indeterminate = _is_indeterminate(outcomes)

    result = {
        "retrieval": [
            {
                "date": o.date,
                "edition": o.edition,
                "status": o.status,
                "http_status": o.http_status,
                "absent_is_provisional": o.absent_is_provisional,
                "classification_note": o.classification_note,
                "attempts": o.attempts,
                "elapsed_s": round(o.elapsed_s, 3),
                "source": o.source,
                "report_effective_utc": o.report_effective_utc,
                "edition_token_utc": o.edition_token_utc,
                "source_last_modified_utc": o.source_last_modified_utc,
                "fetched_at_utc": o.fetched_at_utc,
            }
            for o in outcomes
        ],
        "parsed": {f"{d} {e}": v for (d, e), v in parse_summaries.items()},
        "identity": {
            "player": dict(player_counts),
            "team": dict(team_counts),
            "examples_unmatched_player": [
                m.row.player_name for m in matches if m.player_match == "unmatched"
            ][:EXAMPLE_CAP],
            "examples_ambiguous_player": [
                m.row.player_name for m in matches if m.player_match == "ambiguous"
            ][:EXAMPLE_CAP],
        },
        "archive_limitation": {
            "absent": absent_editions,
            "failed": failed_editions,
            "absent_caveat": _ABSENT_CAVEAT if absent_editions else None,
        },
        "indeterminate": indeterminate,
    }

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print("=== retrieval outcomes ===")
        for o in outcomes:
            print(
                f"  {o.date} {o.edition:6} status={o.status:6} http={o.http_status} "
                f"attempts={o.attempts} elapsed={o.elapsed_s:.2f}s source={o.source} "
                f"report_effective_utc={o.report_effective_utc} "
                f"edition_token_utc={o.edition_token_utc} "
                f"source_last_modified_utc={o.source_last_modified_utc} "
                f"fetched_at_utc={o.fetched_at_utc}"
            )
        if absent_editions:
            print(f"\n  CAVEAT: {len(absent_editions)} {_ABSENT_CAVEAT}")
        if indeterminate:
            print(
                f"\n  INDETERMINATE: 0 'ok' outcomes out of {len(outcomes)}, "
                f"{len(absent_editions)} provisional-absent. This run produced no usable "
                f"data — treat as a possible access-policy change, not a quiet day, until "
                f"investigated."
            )

        print("\n=== parsed row counts ===")
        for key, v in parse_summaries.items():
            print(
                f"  {key[0]} {key[1]:6} rows_parsed={v['rows_parsed']} "
                f"unparseable_lines={v['unparseable_lines']} "
                f"suspected_truncated_names={v['suspected_truncated_names']}"
            )

        print("\n=== identity matching ===")
        print(f"  player: {dict(player_counts)}")
        print(f"  team:   {dict(team_counts)}")
        if result["identity"]["examples_unmatched_player"]:
            print(f"  unmatched examples: {result['identity']['examples_unmatched_player']}")
        if result["identity"]["examples_ambiguous_player"]:
            print(f"  ambiguous examples: {result['identity']['examples_ambiguous_player']}")

        print("\n=== archive limitation ===")
        print(f"  absent: {absent_editions or 'none'}")
        print(f"  failed: {failed_editions or 'none'}")
        print(f"  indeterminate: {indeterminate}")

    return 1 if (failed_editions or indeterminate) else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", action="append", dest="dates", default=None)
    parser.add_argument(
        "--editions",
        default="",
        help="Comma list of edition tokens. Default: chosen per date (legacy 05PM/08PM "
             "before 2025-12-22, modern 12_45PM/05_30PM/08_30PM from then on).",
    )
    parser.add_argument("--cache-dir", default=None, help="override the PDF disk-cache dir (default: scoutiq/data/raw/injury_reports)")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    dates = args.dates or list(DEFAULT_DATES)
    editions = [e.strip() for e in args.editions.split(",") if e.strip()]

    exit_code = run(
        dates,
        editions,
        use_cache=not args.no_cache,
        pause=args.pause,
        timeout=args.timeout,
        as_json=args.as_json,
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
