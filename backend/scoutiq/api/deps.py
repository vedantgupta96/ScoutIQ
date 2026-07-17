"""FastAPI dependency providers."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from scoutiq.db import SessionLocal


def get_db() -> Iterator[Session]:
    if SessionLocal is None:
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


DB = Annotated[Session, Depends(get_db)]
