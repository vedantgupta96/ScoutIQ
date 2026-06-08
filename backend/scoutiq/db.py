"""SQLAlchemy 2.0 engine + session factory."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from scoutiq.config import settings


def _make_engine():
    if not settings.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is empty. Copy backend/.env.example to backend/.env and paste your "
            "Neon connection string (with the postgresql+psycopg:// prefix and ?sslmode=require)."
        )
    # pool_pre_ping avoids stale-connection errors against Neon's autosuspend;
    # pool_recycle proactively retires connections before Neon would drop them.
    return create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )


engine = _make_engine() if settings.DATABASE_URL else None
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True) if engine else None


@contextmanager
def get_session() -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on error."""
    if SessionLocal is None:
        # Re-build lazily so importing this module never crashes before .env is set.
        raise RuntimeError("No DB engine — set DATABASE_URL in backend/.env first.")
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
