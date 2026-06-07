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

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
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
    current_team_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("teams.team_id"))
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
    __table_args__ = (UniqueConstraint("player_id", "season", name="uq_player_season"),)

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
    __table_args__ = (UniqueConstraint("player_id", "season_start", name="uq_contract_player_start"),)

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
    __table_args__ = (UniqueConstraint("contract_id", "season", name="uq_contract_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(Integer, ForeignKey("contracts.id"), index=True)
    season: Mapped[str] = mapped_column(String(7), index=True)
    aav: Mapped[int | None] = mapped_column(BigInteger)          # dollars this season
    cap_pct: Mapped[float | None] = mapped_column(Numeric(6, 4)) # fraction (0.20 = 20% of cap)
    is_guaranteed: Mapped[bool] = mapped_column(Boolean, default=True)
    is_player_option: Mapped[bool] = mapped_column(Boolean, default=False)
    is_team_option: Mapped[bool] = mapped_column(Boolean, default=False)

    contract: Mapped[Contract] = relationship(back_populates="contract_years")
