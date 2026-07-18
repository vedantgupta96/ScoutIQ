"""
ScoutIQ ORM models (data layer, v0).

Design choices:
- Natural keys: `players.player_id` and `teams.team_id` ARE the nba_api IDs (BigInteger). This means the
  stats ETL needs no surrogate-key crosswalk — nba data joins directly.
- `player_seasons.box` / `.advanced` are JSONB: stat sets are wide and evolve; we filter on a few typed
  columns (season, age, gp, min) and keep the rest flexible. `advanced` merges nba.com + BBRef metrics.
- `player_salaries` holds *realized historical* salary (from BBRef) — the v0 model target.
- `player_xref` solves nba_id -> BBRef slug exactly once.
- contracts/contract_years (forward structure, Spotrac) are intentionally NOT defined yet — later phase.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    team_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # nba_api TEAM_ID
    abbreviation: Mapped[str | None] = mapped_column(String(8))
    name: Mapped[str | None] = mapped_column(String(64))
    conference: Mapped[str | None] = mapped_column(String(16))
    division: Mapped[str | None] = mapped_column(String(32))


class Player(Base):
    __tablename__ = "players"

    player_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # nba_api PLAYER_ID
    full_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    position: Mapped[str | None] = mapped_column(String(16))  # filled from BBRef advanced table
    current_team_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("teams.team_id"), index=True)
    current_team_source: Mapped[str | None] = mapped_column(String(64))
    current_team_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    xref: Mapped["PlayerXref | None"] = relationship(back_populates="player", uselist=False)


class PlayerXref(Base):
    """nba_api player_id <-> verified Basketball-Reference slug. Solves name-matching once."""
    __tablename__ = "player_xref"

    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.player_id"), primary_key=True
    )
    bbref_slug: Mapped[str | None] = mapped_column(String(16), index=True)
    verified_name: Mapped[str | None] = mapped_column(String(128))
    # 'verified' | 'mismatch' | 'not_found' — honesty about match quality for later auditing.
    status: Mapped[str] = mapped_column(String(16), default="unverified")

    player: Mapped[Player] = relationship(back_populates="xref")


class PlayerSeason(Base):
    __tablename__ = "player_seasons"
    __table_args__ = (
        UniqueConstraint("player_id", "season", name="uq_player_season"),
        Index("ix_player_seasons_season_minutes", "season", "minutes"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    season: Mapped[str] = mapped_column(String(7), index=True)  # '2023-24'
    team_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("teams.team_id"))
    age: Mapped[int | None] = mapped_column(Integer)
    gp: Mapped[int | None] = mapped_column(Integer)
    minutes: Mapped[float | None] = mapped_column(Numeric)
    box: Mapped[dict | None] = mapped_column(JSONB)        # nba.com Base box stats
    advanced: Mapped[dict | None] = mapped_column(JSONB)   # nba.com Advanced + BBRef BPM/VORP/WS/...


class PlayerSalary(Base):
    """Realized historical salary per season (from BBRef). The v0 valuation target source."""
    __tablename__ = "player_salaries"
    __table_args__ = (UniqueConstraint("player_id", "season", name="uq_player_salary_season"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    season: Mapped[str] = mapped_column(String(7), index=True)
    salary: Mapped[int | None] = mapped_column(BigInteger)  # dollars
    source: Mapped[str] = mapped_column(String(32), default="bbref")


class CapConstants(Base):
    """League cap parameters per season. Data, not code — they change every year."""
    __tablename__ = "cap_constants"

    season: Mapped[str] = mapped_column(String(7), primary_key=True)
    salary_cap: Mapped[int | None] = mapped_column(BigInteger)
    tax_line: Mapped[int | None] = mapped_column(BigInteger)
    first_apron: Mapped[int | None] = mapped_column(BigInteger)   # null before 2023-24 CBA
    second_apron: Mapped[int | None] = mapped_column(BigInteger)  # null before 2023-24 CBA
    max_25: Mapped[int | None] = mapped_column(BigInteger)        # 0–6 yrs experience
    max_30: Mapped[int | None] = mapped_column(BigInteger)        # 7–9 yrs
    max_35: Mapped[int | None] = mapped_column(BigInteger)        # 10+ yrs


class Contract(Base):
    """Forward contract structure from Spotrac — what the player is OWED, not what they earned."""
    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("player_id", "season_start", name="uq_contract_player_start"),
        Index("ix_contracts_player_latest", "player_id", "season_start", "scraped_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    team_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("teams.team_id"))
    season_start: Mapped[str] = mapped_column(String(7))   # e.g. '2024-25'
    years: Mapped[int] = mapped_column(Integer)
    total_value: Mapped[int | None] = mapped_column(BigInteger)  # total dollars across all years
    source: Mapped[str] = mapped_column(String(32), default="spotrac")
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    contract_years: Mapped[list["ContractYear"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", order_by="ContractYear.season"
    )


class ContractYear(Base):
    """One season of a Contract — the year-by-year cap hit used by the cap simulator."""
    __tablename__ = "contract_years"
    __table_args__ = (
        UniqueConstraint("contract_id", "season", name="uq_contract_year"),
        Index("ix_contract_years_season_contract_id", "season", "contract_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(Integer, ForeignKey("contracts.id"), index=True)
    season: Mapped[str] = mapped_column(String(7), index=True)
    aav: Mapped[int | None] = mapped_column(BigInteger)          # dollars this season
    cap_pct: Mapped[float | None] = mapped_column(Numeric(6, 4)) # fraction (0.20 = 20% of cap)
    is_guaranteed: Mapped[bool] = mapped_column(Boolean, default=True)
    is_player_option: Mapped[bool] = mapped_column(Boolean, default=False)
    is_team_option: Mapped[bool] = mapped_column(Boolean, default=False)

    contract: Mapped[Contract] = relationship(back_populates="contract_years")


class FreeAgentRight(Base):
    """Spotrac-sourced free-agent status and team-salary rights for one offseason."""
    __tablename__ = "free_agent_rights"
    __table_args__ = (
        UniqueConstraint("player_id", "entering_season", name="uq_free_agent_right_player_season"),
        Index("ix_free_agent_rights_season_team", "entering_season", "rights_team_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    entering_season: Mapped[str] = mapped_column(String(7))
    rights_team_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("teams.team_id"), index=True)
    # Controlled values: ufa | rfa. Null is allowed for cap-hold-only source rows.
    fa_status: Mapped[str | None] = mapped_column(String(8))
    # Controlled values: bird | early-bird | non-bird | two-way.
    bird_rights: Mapped[str | None] = mapped_column(String(16))
    qualifying_offer_usd: Mapped[int | None] = mapped_column(BigInteger)
    cap_hold_usd: Mapped[int | None] = mapped_column(BigInteger)
    previous_aav_usd: Mapped[int | None] = mapped_column(BigInteger)
    source_player_id: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32), default="spotrac")
    source_url: Mapped[str | None] = mapped_column(String(512))
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScoutReport(Base):
    """A qualitative scouting narrative sourced from Perplexity Sonar (WORDS only, with citations).

    `source_text` is the narrative the LLM later extracts ratings from; `citations` preserves the
    Sonar source URLs so every derived rating is traceable. Never holds stats/salary/cap numbers.
    """
    __tablename__ = "scout_reports"

    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # stable, e.g. 'sonar-{pid}-{season}'
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    season: Mapped[str] = mapped_column(String(7))
    source_label: Mapped[str] = mapped_column(String(64))  # e.g. 'Perplexity Sonar'
    source_text: Mapped[str] = mapped_column(String)       # the narrative (TEXT)
    citations: Mapped[list | None] = mapped_column(JSONB)  # list[str] of source URLs
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ratings: Mapped[list["PlayerRating"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class PlayerRating(Base):
    """One Claude-extracted, schema-validated trait rating for a ScoutReport.

    Mirrors `llm.schemas.ScoutRating` (trait/score/confidence/evidence_span). Model-extracted from a
    public narrative — not official scouting.
    """
    __tablename__ = "player_ratings"
    __table_args__ = (
        UniqueConstraint("report_id", "trait", name="uq_player_rating_report_trait"),
        Index("ix_player_ratings_player_id", "player_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(String(64), ForeignKey("scout_reports.report_id"), index=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    trait: Mapped[str] = mapped_column(String(32))
    score: Mapped[int] = mapped_column(Integer)             # 1-5
    confidence: Mapped[str] = mapped_column(String(8))      # low | medium | high
    evidence_span: Mapped[str] = mapped_column(String)      # verbatim span from source_text (TEXT)

    report: Mapped[ScoutReport] = relationship(back_populates="ratings")


class PlayerValuation(Base):
    """Precomputed model valuation for one player-season.

    Published by `python -m scoutiq.model.publish_valuations` after ETL/retrain runs; the
    API's read surfaces serve these rows instead of running the model per request. Rows are
    deterministic between data refreshes, so recompute belongs at publish time, not read time.
    """
    __tablename__ = "player_valuations"
    __table_args__ = (
        UniqueConstraint("player_id", "season", name="uq_player_valuation_season"),
        Index("ix_player_valuations_season_gap", "season", "gap_pct"),
        Index("ix_player_valuations_season_value", "season", "value_pct"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    season: Mapped[str] = mapped_column(String(7), index=True)
    value_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    lo_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    hi_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    actual_usd: Mapped[int | None] = mapped_column(BigInteger)
    actual_pct: Mapped[float | None] = mapped_column(Numeric(6, 2))
    gap_pct: Mapped[float | None] = mapped_column(Numeric(6, 2))
    # Watchlist qualification (gp/minutes floors) evaluated at publish time.
    qualified: Mapped[bool] = mapped_column(Boolean, default=False)
    verdict_label: Mapped[str] = mapped_column(String(48))
    verdict_tone: Mapped[str] = mapped_column(String(12))
    caution_flags: Mapped[list | None] = mapped_column(JSONB)
    caveat: Mapped[str | None] = mapped_column(String)
    stats: Mapped[dict | None] = mapped_column(JSONB)     # card stat line + league percentiles
    features: Mapped[dict | None] = mapped_column(JSONB)  # model inputs, for attribution/display
    model_version: Mapped[str] = mapped_column(String(48))
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlayerRationale(Base):
    """A grounded, cited natural-language verdict fusing the model's value gap with the scouting signal.

    Generated live by the rationale endpoint and cached here per (player, consensus_mode). Records token
    usage + estimated cost so the two consensus modes can be compared.
    """
    __tablename__ = "player_rationales"
    __table_args__ = (UniqueConstraint("player_id", "consensus_mode", name="uq_player_rationale_mode"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    consensus_mode: Mapped[str] = mapped_column(String(16))   # fusion | multi_source
    rationale_text: Mapped[str] = mapped_column(String)       # the generated verdict (TEXT)
    citations: Mapped[list | None] = mapped_column(JSONB)     # list[str] of source URLs
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    est_cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    model: Mapped[str | None] = mapped_column(String(48))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
