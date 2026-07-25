"""GET /data-provenance — where each ScoutIQ dataset comes from, how much of it there
is, and when it was last refreshed. Read-only, and deliberately separate from Trade
Lab: no trade workspace/scenario data is ever surfaced here.

Each dataset is queried independently and degrades on its own — one dataset's query
failing never 500s the whole response, consistent with docs/adr/0001 (valuation
surfaces degrade when the model is unavailable). On Postgres, a failed statement
aborts the whole transaction until rolled back, so each dataset runs inside its own
SAVEPOINT (`db.begin_nested()`) — a failure there rolls back just that savepoint,
leaving the shared transaction usable for every dataset queried after it.

Every builder computes counts/spans with SQL aggregates and never selects the
sensitive payload columns (stat JSON, valuation payloads, scout report bodies/
citations, rating evidence spans) — only the columns needed to count and label.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, select
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


class SourceBreakdown(BaseModel):
    source: str
    count: int


class DatasetProvenance(BaseModel):
    """One dataset's source, coverage, and freshness.

    `record_count` is the row count in the dataset's primary table; its exact
    definition (one row per what) varies per dataset and is spelled out in `caveat`.
    `player_count` / `season_count` / `earliest_season` / `latest_season` are filled
    in only where a player or season dimension is meaningful. `last_updated_utc` is
    the latest known source/ingestion timestamp on file for the dataset — null means
    no such timestamp is stored, not that the data is stale or fresh. `source` is a
    stable label: for datasets with a source column, it's source names only —
    ordered by count desc then name asc, no counts, deterministic on ties; for
    datasets without one, it's a fixed descriptive string. `source_breakdown` carries
    the same order with per-source counts for datasets with a source column, and is
    empty for datasets without one.
    """

    key: str
    name: str
    source: str
    source_breakdown: list[SourceBreakdown] = Field(default_factory=list)
    record_count: int | None = None
    player_count: int | None = None
    season_count: int | None = None
    earliest_season: str | None = None
    latest_season: str | None = None
    last_updated_utc: str | None = None
    last_updated_basis: str | None = None
    caveat: str


class ProvenanceResponse(BaseModel):
    """The full provenance snapshot. Every field on every `DatasetProvenance` record,
    and the response itself, is deterministic for a fixed database — the same query
    against the same data always produces the same value. `data_as_of_utc` is the max
    of every dataset's `last_updated_utc` on file — the freshest ingestion timestamp
    among them — or null when every dataset's is null. It is never wall-clock time."""

    datasets: list[DatasetProvenance]
    data_as_of_utc: str | None = None
    caveat: str


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _grouped_source(db: Session, col, where=None) -> list:
    """Group `col` and return its (value, count) distribution, ordered by count desc
    then value asc — an explicit tie-break so equal counts still sort deterministically.
    Null values are skipped. Empty list if there are no rows."""
    stmt = select(col, func.count()).where(col.isnot(None))
    if where is not None:
        stmt = stmt.where(where)
    stmt = stmt.group_by(col).order_by(func.count().desc(), col.asc())
    return db.execute(stmt).all()


def _source_fields(pairs, fallback: str) -> tuple[str, list[SourceBreakdown]]:
    """Build the stable `source` label and `source_breakdown` list from a
    `_grouped_source` result. `fallback` covers the no-rows case: a descriptive
    source label with an empty breakdown."""
    if not pairs:
        return fallback, []
    return ", ".join(value for value, _ in pairs), [SourceBreakdown(source=value, count=count) for value, count in pairs]


def _unavailable(key: str, name: str, error: Exception) -> DatasetProvenance:
    logger.warning("data-provenance dataset %s query failed: %s", key, error.__class__.__name__)
    return DatasetProvenance(
        key=key,
        name=name,
        source="Source unavailable",
        caveat=f"{name} is temporarily unavailable — its query failed; other datasets are unaffected.",
    )


def _player_seasons(db: Session) -> DatasetProvenance:
    key, name, source = "player_seasons", "Player seasons & statistics", "nba.com Advanced + Basketball-Reference"
    record_count = db.scalar(select(func.count()).select_from(PlayerSeason))
    player_count = db.scalar(select(func.count(distinct(PlayerSeason.player_id))))
    season_count = db.scalar(select(func.count(distinct(PlayerSeason.season))))
    earliest = db.scalar(select(func.min(PlayerSeason.season)))
    latest = db.scalar(select(func.max(PlayerSeason.season)))
    return DatasetProvenance(
        key=key,
        name=name,
        source=source,
        record_count=record_count,
        player_count=player_count,
        season_count=season_count,
        earliest_season=earliest,
        latest_season=latest,
        caveat=(
            "record_count is rows in player_seasons (one per player-season); player_count is "
            "distinct players with a stat row; season_count/earliest/latest span the seasons on "
            "file. Advanced metrics merge nba.com Advanced with Basketball-Reference. "
            "player_seasons has no per-row source column, so this label is descriptive, not a "
            "grouped count. No ingestion timestamp is stored for this table, so freshness is "
            "unknown, not assumed current."
        ),
    )


def _player_salaries(db: Session) -> DatasetProvenance:
    key, name = "player_salaries", "Realized pay (player salaries)"
    source, source_breakdown = _source_fields(_grouped_source(db, PlayerSalary.source), "no source recorded")
    record_count = db.scalar(select(func.count()).select_from(PlayerSalary))
    player_count = db.scalar(select(func.count(distinct(PlayerSalary.player_id))))
    season_count = db.scalar(select(func.count(distinct(PlayerSalary.season))))
    earliest = db.scalar(select(func.min(PlayerSalary.season)))
    latest = db.scalar(select(func.max(PlayerSalary.season)))
    return DatasetProvenance(
        key=key,
        name=name,
        source=source,
        source_breakdown=source_breakdown,
        record_count=record_count,
        player_count=player_count,
        season_count=season_count,
        earliest_season=earliest,
        latest_season=latest,
        caveat=(
            "record_count is rows in player_salaries (one per player-season of realized pay); "
            "player_count is distinct players; season_count/earliest/latest span the seasons on "
            "file. source is the distribution of player_salaries.source values, most common "
            "first. No ingestion timestamp is stored, so freshness is unknown, not assumed "
            "current."
        ),
    )


def _contracts(db: Session) -> DatasetProvenance:
    key, name = "contracts", "Forward contracts"
    source, source_breakdown = _source_fields(_grouped_source(db, Contract.source), "no source recorded")
    record_count = db.scalar(select(func.count()).select_from(ContractYear))
    player_count = db.scalar(select(func.count(distinct(Contract.player_id))))
    season_count = db.scalar(select(func.count(distinct(ContractYear.season))))
    earliest = db.scalar(select(func.min(ContractYear.season)))
    latest = db.scalar(select(func.max(ContractYear.season)))
    last_updated = db.scalar(select(func.max(Contract.scraped_at)))
    return DatasetProvenance(
        key=key,
        name=name,
        source=source,
        source_breakdown=source_breakdown,
        record_count=record_count,
        player_count=player_count,
        season_count=season_count,
        earliest_season=earliest,
        latest_season=latest,
        last_updated_utc=_iso(last_updated),
        last_updated_basis="contracts.scraped_at" if last_updated is not None else None,
        caveat=(
            "record_count is rows in contract_years (one per contract-season); player_count is "
            "distinct players with a forward contract; season_count/earliest/latest span "
            "contract_years.season. source is the distribution of contracts.source values, most "
            "common first. last_updated_utc is the most recent contracts.scraped_at across all "
            "contracts — when a contract was last scraped for any player, not a per-player "
            "freshness guarantee."
        ),
    )


def _cap_constants(db: Session) -> DatasetProvenance:
    key, name, source = "cap_constants", "Salary cap constants", "CBA / league"
    record_count = db.scalar(select(func.count()).select_from(CapConstants))
    season_count = db.scalar(select(func.count(distinct(CapConstants.season))))
    earliest = db.scalar(select(func.min(CapConstants.season)))
    latest = db.scalar(select(func.max(CapConstants.season)))
    return DatasetProvenance(
        key=key,
        name=name,
        source=source,
        record_count=record_count,
        season_count=season_count,
        earliest_season=earliest,
        latest_season=latest,
        caveat=(
            "record_count/season_count is rows in cap_constants (one per season); "
            "earliest/latest span the seasons on file. These are hand/CBA-maintained constants, "
            "not scraped; cap_constants has no per-row source column, so this label is "
            "descriptive, not a grouped count. No ingestion timestamp is stored, so freshness is "
            "unknown, not assumed current."
        ),
    )


def _free_agent_rights(db: Session) -> DatasetProvenance:
    key, name = "free_agent_rights", "Free-agent rights"
    source, source_breakdown = _source_fields(_grouped_source(db, FreeAgentRight.source), "no source recorded")
    record_count = db.scalar(select(func.count()).select_from(FreeAgentRight))
    player_count = db.scalar(select(func.count(distinct(FreeAgentRight.player_id))))
    season_count = db.scalar(select(func.count(distinct(FreeAgentRight.entering_season))))
    earliest = db.scalar(select(func.min(FreeAgentRight.entering_season)))
    latest = db.scalar(select(func.max(FreeAgentRight.entering_season)))
    last_updated = db.scalar(select(func.max(FreeAgentRight.scraped_at)))
    return DatasetProvenance(
        key=key,
        name=name,
        source=source,
        source_breakdown=source_breakdown,
        record_count=record_count,
        player_count=player_count,
        season_count=season_count,
        earliest_season=earliest,
        latest_season=latest,
        last_updated_utc=_iso(last_updated),
        last_updated_basis="free_agent_rights.scraped_at" if last_updated is not None else None,
        caveat=(
            "record_count is rows in free_agent_rights (one per player per entering season); "
            "player_count is distinct players; season_count/earliest/latest span "
            "entering_season. source is the distribution of free_agent_rights.source values, "
            "most common first. last_updated_utc is the most recent "
            "free_agent_rights.scraped_at across all rows."
        ),
    )


def _rosters(db: Session) -> DatasetProvenance:
    key, name = "rosters", "Current roster assignments"
    has_team = Player.current_team_id.isnot(None)
    source, source_breakdown = _source_fields(
        _grouped_source(db, Player.current_team_source, where=has_team), "no source recorded"
    )
    with_team = db.scalar(select(func.count()).select_from(Player).where(has_team))
    last_updated = db.scalar(select(func.max(Player.current_team_updated_at)))
    return DatasetProvenance(
        key=key,
        name=name,
        source=source,
        source_breakdown=source_breakdown,
        record_count=with_team,
        player_count=with_team,
        last_updated_utc=_iso(last_updated),
        last_updated_basis="players.current_team_updated_at" if last_updated is not None else None,
        caveat=(
            f"record_count/player_count is players carrying a current_team_id ({with_team}) — "
            "current-roster assignment coverage only. source is the distribution of "
            "players.current_team_source values among those players, most common first. "
            "Two-way status is tracked as its own dataset (two_way_status) with its own "
            "freshness, not folded into this one. last_updated_utc is the most recent "
            "players.current_team_updated_at across all players."
        ),
    )


def _two_way_status(db: Session) -> DatasetProvenance:
    key, name, source = "two_way_status", "Two-way contract flags", "Spotrac (load_two_way_status ETL)"
    two_way = db.scalar(select(func.count()).select_from(Player).where(Player.is_two_way.is_(True)))
    total = db.scalar(select(func.count()).select_from(Player))
    return DatasetProvenance(
        key=key,
        name=name,
        source=source,
        record_count=two_way,
        player_count=total,
        caveat=(
            f"record_count is players flagged is_two_way ({two_way}); player_count is total "
            f"players considered ({total}), the denominator. is_two_way defaults to false with "
            "no observed/loaded marker, so a player who is genuinely not two-way can't be "
            "distinguished from one whose flag was never loaded — record_count is players "
            "currently flagged true out of all tracked players, not a verified two-way count. "
            "The load_two_way_status ETL does not record its own run time, so "
            "last_updated_utc/last_updated_basis are always null here — two-way freshness is "
            "unknown, and it must not be read as inheriting the current-roster-assignment "
            "timestamp from the rosters dataset. A record_count of 0 may indicate the "
            "load_two_way_status ETL has not populated the flag — unloaded, not evidence that no "
            "two-way players exist — exactly the kind of coverage fact this provenance center "
            "exists to surface."
        ),
    )


def _scout_reports(db: Session) -> DatasetProvenance:
    key, name = "scout_reports", "Scout reports & ratings"
    source, source_breakdown = _source_fields(_grouped_source(db, ScoutReport.source_label), "no source recorded")
    record_count = db.scalar(select(func.count()).select_from(ScoutReport))
    player_count = db.scalar(select(func.count(distinct(ScoutReport.player_id))))
    season_count = db.scalar(select(func.count(distinct(ScoutReport.season))))
    earliest = db.scalar(select(func.min(ScoutReport.season)))
    latest = db.scalar(select(func.max(ScoutReport.season)))
    last_updated = db.scalar(select(func.max(ScoutReport.fetched_at)))
    rating_count = db.scalar(select(func.count()).select_from(PlayerRating))
    return DatasetProvenance(
        key=key,
        name=name,
        source=source,
        source_breakdown=source_breakdown,
        record_count=record_count,
        player_count=player_count,
        season_count=season_count,
        earliest_season=earliest,
        latest_season=latest,
        last_updated_utc=_iso(last_updated),
        last_updated_basis="scout_reports.fetched_at" if last_updated is not None else None,
        caveat=(
            "record_count is rows in scout_reports (one per fetched narrative); "
            "player_count/season_count span distinct players/seasons with a report. source is "
            "the distribution of scout_reports.source_label values, most common first. "
            f"{rating_count} trait ratings have been extracted from these reports "
            "(player_ratings). Report bodies, citations, and evidence spans are never exposed "
            "here — counts and timestamps only. These are fixture/LLM-sourced qualitative "
            "context (Sonar narratives, Claude-extracted ratings), not official scouting or "
            "ground truth."
        ),
    )


def _player_valuations(db: Session) -> DatasetProvenance:
    key, name, source = "player_valuations", "Published valuations", "ScoutIQ model"
    record_count = db.scalar(select(func.count()).select_from(PlayerValuation))
    player_count = db.scalar(select(func.count(distinct(PlayerValuation.player_id))))
    season_count = db.scalar(select(func.count(distinct(PlayerValuation.season))))
    earliest = db.scalar(select(func.min(PlayerValuation.season)))
    latest = db.scalar(select(func.max(PlayerValuation.season)))
    last_updated = db.scalar(select(func.max(PlayerValuation.computed_at)))
    versions = db.scalar(select(func.count(distinct(PlayerValuation.model_version))))
    return DatasetProvenance(
        key=key,
        name=name,
        source=source,
        record_count=record_count,
        player_count=player_count,
        season_count=season_count,
        earliest_season=earliest,
        latest_season=latest,
        last_updated_utc=_iso(last_updated),
        last_updated_basis="player_valuations.computed_at" if last_updated is not None else None,
        caveat=(
            "record_count is rows in player_valuations (one per player-season with a published "
            f"model valuation); player_count/season_count/earliest/latest span those rows, "
            f"across {versions} distinct model_version value(s) on file. player_valuations has "
            "no per-row source column beyond model_version, so this label is descriptive, not a "
            "grouped count. last_updated_utc is the most recent computed_at — when valuations "
            "were last published, not when the underlying stats or contracts changed."
        ),
    )


@router.get("", response_model=ProvenanceResponse)
def get_data_provenance(db: DB = None) -> ProvenanceResponse:
    """One record per dataset — source, coverage, and freshness. Never trade data.

    Each builder runs inside its own SAVEPOINT: a query failure there rolls back
    only that savepoint, so it degrades to _unavailable(...) without poisoning the
    shared transaction the other datasets query from.
    """
    builders: list[tuple[str, str, Callable[[Session], DatasetProvenance]]] = [
        ("player_seasons", "Player seasons & statistics", _player_seasons),
        ("player_salaries", "Realized pay (player salaries)", _player_salaries),
        ("contracts", "Forward contracts", _contracts),
        ("cap_constants", "Salary cap constants", _cap_constants),
        ("free_agent_rights", "Free-agent rights", _free_agent_rights),
        ("rosters", "Current roster assignments", _rosters),
        ("two_way_status", "Two-way contract flags", _two_way_status),
        ("scout_reports", "Scout reports & ratings", _scout_reports),
        ("player_valuations", "Published valuations", _player_valuations),
    ]
    datasets: list[DatasetProvenance] = []
    for key, name, builder in builders:
        try:
            with db.begin_nested():
                datasets.append(builder(db))
        except Exception as exc:  # noqa: BLE001 - each dataset must degrade independently
            datasets.append(_unavailable(key, name, exc))
    known_timestamps = [d.last_updated_utc for d in datasets if d.last_updated_utc is not None]
    return ProvenanceResponse(
        datasets=datasets,
        data_as_of_utc=max(known_timestamps) if known_timestamps else None,
        caveat=TOP_LEVEL_CAVEAT,
    )
