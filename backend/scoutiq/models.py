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

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, String, UniqueConstraint
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
