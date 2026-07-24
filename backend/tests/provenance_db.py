"""A real (SQLite, in-memory) Session for data-provenance router tests.

The ORM models use Postgres-only column types (JSONB) that SQLite can't build via
`Base.metadata.create_all`, so this creates only the tables/columns the provenance
queries actually touch, via raw `text()` DDL. The router's `select(func.count(...))`
/ `select(func.min/max(...))` statements are built from the ORM's typed column
objects (e.g. `Contract.scraped_at`), so they compile and run correctly against
these tables even though the tables were never created from the full ORM metadata —
as long as no query in the router selects a column missing from the DDL below,
which is also exactly the invariant F1 depends on (sensitive columns are never
selected, so they never need to exist here).
"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

_DDL = (
    """
    CREATE TABLE players (
        player_id INTEGER PRIMARY KEY,
        current_team_id INTEGER,
        current_team_source TEXT,
        current_team_updated_at TIMESTAMP,
        is_two_way BOOLEAN
    )
    """,
    """
    CREATE TABLE player_seasons (
        id INTEGER PRIMARY KEY,
        player_id INTEGER,
        season TEXT
    )
    """,
    """
    CREATE TABLE player_salaries (
        id INTEGER PRIMARY KEY,
        player_id INTEGER,
        season TEXT,
        source TEXT
    )
    """,
    """
    CREATE TABLE contracts (
        id INTEGER PRIMARY KEY,
        player_id INTEGER,
        source TEXT,
        scraped_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE contract_years (
        id INTEGER PRIMARY KEY,
        contract_id INTEGER,
        season TEXT
    )
    """,
    """
    CREATE TABLE cap_constants (
        season TEXT PRIMARY KEY
    )
    """,
    """
    CREATE TABLE free_agent_rights (
        id INTEGER PRIMARY KEY,
        player_id INTEGER,
        entering_season TEXT,
        source TEXT,
        scraped_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE scout_reports (
        report_id TEXT PRIMARY KEY,
        player_id INTEGER,
        season TEXT,
        source_label TEXT,
        fetched_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE player_ratings (
        id INTEGER PRIMARY KEY,
        report_id TEXT,
        player_id INTEGER
    )
    """,
    """
    CREATE TABLE player_valuations (
        id INTEGER PRIMARY KEY,
        player_id INTEGER,
        season TEXT,
        computed_at TIMESTAMP,
        model_version TEXT
    )
    """,
)


def make_session() -> Session:
    """A fresh in-memory SQLite Session with the provenance tables created (empty)."""
    # StaticPool + check_same_thread=False: one shared connection backs the in-memory
    # DB, so the tables created/seeded here are visible when the TestClient runs the
    # endpoint on a different thread (default per-connection :memory: would be empty there).
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        for stmt in _DDL:
            conn.execute(text(stmt))
    return Session(engine)


def seed(db: Session, *, table: str, rows: list[dict]) -> None:
    """Insert `rows` (each a column-name -> value dict) into `table`."""
    if not rows:
        return
    columns = rows[0].keys()
    stmt = text(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
        f"({', '.join(f':{c}' for c in columns)})"
    )
    db.execute(stmt, rows)
    db.commit()
