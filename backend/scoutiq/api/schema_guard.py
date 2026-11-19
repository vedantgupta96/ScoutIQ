"""Deploy-order guard for columns added by migrations that may not have run yet."""
from __future__ import annotations

from sqlalchemy import inspect

_present: set[tuple[str, str]] = set()


def column_exists(db, table: str, column: str) -> bool:
    key = (table, column)
    if key in _present:
        return True
    try:
        found = any(c["name"] == column for c in inspect(db.get_bind()).get_columns(table))
    except Exception:
        return False
    if found:
        _present.add(key)
    return found


def contract_remaining_guaranteed(db, contract_id: int) -> int | None:
    """Source-reported remaining guaranteed total, or None when unknown or migration 0013 has not run."""
    if not column_exists(db, "contracts", "remaining_guaranteed_usd"):
        return None
    from sqlalchemy import select

    from scoutiq.models import Contract

    return db.scalar(select(Contract.remaining_guaranteed_usd).where(Contract.id == contract_id))
