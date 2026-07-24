"""GET /data-provenance — where each ScoutIQ dataset comes from, how much of it there
is, and when it was last refreshed. Read-only, and deliberately separate from Trade
Lab: no trade workspace/scenario data is ever surfaced here.

Each dataset is queried independently and degrades on its own — one dataset's query
failing never 500s the whole response, consistent with docs/adr/0001 (valuation
surfaces degrade when the model is unavailable).
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from scoutiq.api.deps import DB
from scoutiq.models import (
    CapConstants,
    Contract,
    ContractYear,
    FreeAgentRight,
    Player,
    PlayerRating,
    PlayerSalary,
    PlayerSeason,
    PlayerValuation,
    ScoutReport,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data-provenance", tags=["data-provenance"])

TOP_LEVEL_CAVEAT = (
    "Provenance describes what each dataset covers and how fresh it is — it is not a "
    "data-quality guarantee. A null last_updated_utc means no ingestion timestamp is "
    "stored for that dataset, never a guess at one. This response never includes trade "
    "workspace/scenario data, report bodies, citations, or raw evidence text."
)


class DatasetProvenance(BaseModel):
    """One dataset's source, coverage, and freshness.

    `record_count` is the row count in the dataset's primary table; its exact
    definition (one row per what) varies per dataset and is spelled out in `caveat`.
    `player_count` / `season_count` / `earliest_season` / `latest_season` are filled
    in only where a player or season dimension is meaningful. `last_updated_utc` is
    the latest known source/ingestion timestamp on file for the dataset — null means
    no such timestamp is stored, not that the data is stale or fresh.
    """

    key: str
    name: str
    source: str
    record_count: int | None = None
    player_count: int | None = None
    season_count: int | None = None
    earliest_season: str | None = None
    latest_season: str | None = None
    last_updated_utc: str | None = None
    last_updated_basis: str | None = None
    caveat: str


class ProvenanceResponse(BaseModel):
    datasets: list[DatasetProvenance]
    generated_at_utc: str
    caveat: str


def _season_span(seasons: Iterable[str | None]) -> tuple[int, str | None, str | None]:
    uniq = sorted({s for s in seasons if s})
    if not uniq:
        return 0, None, None
    return len(uniq), uniq[0], uniq[-1]


def _latest(timestamps: Iterable[datetime | None]) -> datetime | None:
    present = [dt for dt in timestamps if dt is not None]
    return max(present) if present else None


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _unavailable(key: str, name: str, source: str, error: Exception) -> DatasetProvenance:
    logger.warning("data-provenance dataset %s query failed: %s", key, error.__class__.__name__)
    return DatasetProvenance(
        key=key,
        name=name,
        source=source,
        caveat=f"{name} is temporarily unavailable — its query failed; other datasets are unaffected.",
    )


def _player_seasons(db: Session) -> DatasetProvenance:
    key, name, source = "player_seasons", "Player seasons & statistics", "nba.com Advanced + Basketball-Reference"
    try:
        rows = db.scalars(select(PlayerSeason)).all()
        season_count, earliest, latest = _season_span(r.season for r in rows)
        return DatasetProvenance(
            key=key,
            name=name,
            source=source,
            record_count=len(rows),
            player_count=len({r.player_id for r in rows}),
            season_count=season_count,
            earliest_season=earliest,
            latest_season=latest,
            caveat=(
                "record_count is rows in player_seasons (one per player-season); player_count is "
                "distinct players with a stat row; season_count/earliest/latest span the seasons on "
                "file. Advanced metrics merge nba.com Advanced with Basketball-Reference. No "
                "ingestion timestamp is stored for this table, so freshness is unknown, not assumed "
                "current."
            ),
        )
    except Exception as exc:  # noqa: BLE001 - each dataset must degrade independently
        return _unavailable(key, name, source, exc)


def _player_salaries(db: Session) -> DatasetProvenance:
    key, name, source = "player_salaries", "Realized pay (player salaries)", "Basketball-Reference (bbref)"
    try:
        rows = db.scalars(select(PlayerSalary)).all()
        season_count, earliest, latest = _season_span(r.season for r in rows)
        return DatasetProvenance(
            key=key,
            name=name,
            source=source,
            record_count=len(rows),
            player_count=len({r.player_id for r in rows}),
            season_count=season_count,
            earliest_season=earliest,
            latest_season=latest,
            caveat=(
                "record_count is rows in player_salaries (one per player-season of realized pay); "
                "player_count is distinct players; season_count/earliest/latest span the seasons on "
                "file. The stored source column is 'bbref'. No ingestion timestamp is stored, so "
                "freshness is unknown, not assumed current."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _unavailable(key, name, source, exc)


def _contracts(db: Session) -> DatasetProvenance:
    key, name, source = "contracts", "Forward contracts", "Spotrac"
    try:
        contracts = db.scalars(select(Contract)).all()
        years = db.scalars(select(ContractYear)).all()
        season_count, earliest, latest = _season_span(y.season for y in years)
        last_updated = _latest(c.scraped_at for c in contracts)
        return DatasetProvenance(
            key=key,
            name=name,
            source=source,
            record_count=len(years),
            player_count=len({c.player_id for c in contracts}),
            season_count=season_count,
            earliest_season=earliest,
            latest_season=latest,
            last_updated_utc=_iso(last_updated),
            last_updated_basis="contracts.scraped_at" if last_updated is not None else None,
            caveat=(
                "record_count is rows in contract_years (one per contract-season); player_count is "
                "distinct players with a forward contract; season_count/earliest/latest span "
                "contract_years.season. last_updated_utc is the most recent contracts.scraped_at "
                "across all contracts — when Spotrac was last scraped for any player, not a "
                "per-player freshness guarantee."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _unavailable(key, name, source, exc)


def _cap_constants(db: Session) -> DatasetProvenance:
    key, name, source = "cap_constants", "Salary cap constants", "CBA / league"
    try:
        rows = db.scalars(select(CapConstants)).all()
        season_count, earliest, latest = _season_span(r.season for r in rows)
        return DatasetProvenance(
            key=key,
            name=name,
            source=source,
            record_count=len(rows),
            season_count=season_count,
            earliest_season=earliest,
            latest_season=latest,
            caveat=(
                "record_count/season_count is rows in cap_constants (one per season); "
                "earliest/latest span the seasons on file. These are hand/CBA-maintained constants, "
                "not scraped, and no ingestion timestamp is stored, so freshness is unknown, not "
                "assumed current."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _unavailable(key, name, source, exc)


def _free_agent_rights(db: Session) -> DatasetProvenance:
    key, name, source = "free_agent_rights", "Free-agent rights", "Spotrac"
    try:
        rows = db.scalars(select(FreeAgentRight)).all()
        season_count, earliest, latest = _season_span(r.entering_season for r in rows)
        last_updated = _latest(r.scraped_at for r in rows)
        return DatasetProvenance(
            key=key,
            name=name,
            source=source,
            record_count=len(rows),
            player_count=len({r.player_id for r in rows}),
            season_count=season_count,
            earliest_season=earliest,
            latest_season=latest,
            last_updated_utc=_iso(last_updated),
            last_updated_basis="free_agent_rights.scraped_at" if last_updated is not None else None,
            caveat=(
                "record_count is rows in free_agent_rights (one per player per entering season); "
                "player_count is distinct players; season_count/earliest/latest span "
                "entering_season. last_updated_utc is the most recent free_agent_rights.scraped_at "
                "across all rows."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _unavailable(key, name, source, exc)


def _rosters(db: Session) -> DatasetProvenance:
    key, name, source = "rosters", "Current roster assignments", "Spotrac"
    try:
        players = db.scalars(select(Player)).all()
        with_team = sum(1 for p in players if p.current_team_id is not None)
        last_updated = _latest(p.current_team_updated_at for p in players)
        return DatasetProvenance(
            key=key,
            name=name,
            source=source,
            record_count=with_team,
            player_count=with_team,
            last_updated_utc=_iso(last_updated),
            last_updated_basis="players.current_team_updated_at" if last_updated is not None else None,
            caveat=(
                f"record_count/player_count is players carrying a current_team_id ({with_team}) — "
                "current-roster assignment coverage only. Two-way status is tracked as its own "
                "dataset (two_way_status) with its own freshness, not folded into this one. "
                "last_updated_utc is the most recent players.current_team_updated_at across all "
                "players."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _unavailable(key, name, source, exc)


def _two_way_status(db: Session) -> DatasetProvenance:
    key, name, source = "two_way_status", "Two-way contract flags", "Spotrac (load_two_way_status ETL)"
    try:
        players = db.scalars(select(Player)).all()
        total = len(players)
        two_way = sum(1 for p in players if p.is_two_way)
        return DatasetProvenance(
            key=key,
            name=name,
            source=source,
            record_count=two_way,
            player_count=total,
            caveat=(
                f"record_count is players flagged is_two_way ({two_way}); player_count is total "
                f"players considered ({total}), the denominator. The load_two_way_status ETL does "
                "not record its own run time, so last_updated_utc/last_updated_basis are always null "
                "here — two-way freshness is unknown, and it must not be read as inheriting the "
                "current-roster-assignment timestamp from the rosters dataset. A record_count of 0 "
                "means the load_two_way_status ETL has not populated the flag — unloaded, not "
                "evidence that no two-way players exist — exactly the kind of coverage fact this "
                "provenance center exists to surface."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _unavailable(key, name, source, exc)


def _scout_reports(db: Session) -> DatasetProvenance:
    key, name, source = "scout_reports", "Scout reports & ratings", "Perplexity Sonar"
    try:
        reports = db.scalars(select(ScoutReport)).all()
        ratings = db.scalars(select(PlayerRating)).all()
        season_count, earliest, latest = _season_span(r.season for r in reports)
        last_updated = _latest(r.fetched_at for r in reports)
        return DatasetProvenance(
            key=key,
            name=name,
            source=source,
            record_count=len(reports),
            player_count=len({r.player_id for r in reports}),
            season_count=season_count,
            earliest_season=earliest,
            latest_season=latest,
            last_updated_utc=_iso(last_updated),
            last_updated_basis="scout_reports.fetched_at" if last_updated is not None else None,
            caveat=(
                f"record_count is rows in scout_reports (one per fetched narrative); "
                "player_count/season_count span distinct players/seasons with a report. "
                f"{len(ratings)} trait ratings have been extracted from these reports (player_ratings"
                "). Report bodies, citations, and evidence spans are never exposed here — counts and "
                "timestamps only. These are fixture/LLM-sourced qualitative context (Sonar "
                "narratives, Claude-extracted ratings), not official scouting or ground truth."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _unavailable(key, name, source, exc)


def _player_valuations(db: Session) -> DatasetProvenance:
    key, name, source = "player_valuations", "Published valuations", "ScoutIQ model"
    try:
        rows = db.scalars(select(PlayerValuation)).all()
        season_count, earliest, latest = _season_span(r.season for r in rows)
        last_updated = _latest(r.computed_at for r in rows)
        versions = len({r.model_version for r in rows if r.model_version})
        return DatasetProvenance(
            key=key,
            name=name,
            source=source,
            record_count=len(rows),
            player_count=len({r.player_id for r in rows}),
            season_count=season_count,
            earliest_season=earliest,
            latest_season=latest,
            last_updated_utc=_iso(last_updated),
            last_updated_basis="player_valuations.computed_at" if last_updated is not None else None,
            caveat=(
                "record_count is rows in player_valuations (one per player-season with a published "
                f"model valuation); player_count/season_count/earliest/latest span those rows, across "
                f"{versions} distinct model_version value(s) on file. last_updated_utc is the most "
                "recent computed_at — when valuations were last published, not when the underlying "
                "stats or contracts changed."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _unavailable(key, name, source, exc)


@router.get("", response_model=ProvenanceResponse)
def get_data_provenance(db: DB = None) -> ProvenanceResponse:
    """One record per dataset — source, coverage, and freshness. Never trade data."""
    datasets = [
        _player_seasons(db),
        _player_salaries(db),
        _contracts(db),
        _cap_constants(db),
        _free_agent_rights(db),
        _rosters(db),
        _two_way_status(db),
        _scout_reports(db),
        _player_valuations(db),
    ]
    return ProvenanceResponse(
        datasets=datasets,
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        caveat=TOP_LEVEL_CAVEAT,
    )
