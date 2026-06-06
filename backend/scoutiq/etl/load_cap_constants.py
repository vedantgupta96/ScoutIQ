"""Seed cap_constants from the reference CSV. Idempotent (upsert by season).

max_25 / max_30 / max_35 are computed as 25/30/35% of the cap. NOTE: these are APPROXIMATIONS — the real
max-salary formula differs slightly. Good enough for v0 context features; refine later if needed.
"""
from __future__ import annotations

import csv

from sqlalchemy.dialects.postgresql import insert

from scoutiq.config import DATA_DIR
from scoutiq.db import get_session
from scoutiq.models import CapConstants

SEED = DATA_DIR / "cap_constants_seed.csv"


def _int_or_none(s: str) -> int | None:
    s = (s or "").strip()
    return int(s) if s else None


def run() -> None:
    rows = []
    with SEED.open() as f:
        for r in csv.DictReader(f):
            cap = _int_or_none(r["salary_cap"])
            rows.append(
                {
                    "season": r["season"],
                    "salary_cap": cap,
                    "tax_line": _int_or_none(r["tax_line"]),
                    "first_apron": _int_or_none(r["first_apron"]),
                    "second_apron": _int_or_none(r["second_apron"]),
                    "max_25": round(cap * 0.25) if cap else None,
                    "max_30": round(cap * 0.30) if cap else None,
                    "max_35": round(cap * 0.35) if cap else None,
                }
            )

    with get_session() as s:
        stmt = insert(CapConstants).values(rows)
        update_cols = {c: stmt.excluded[c] for c in rows[0] if c != "season"}
        s.execute(stmt.on_conflict_do_update(index_elements=["season"], set_=update_cols))

    print(f"cap_constants: upserted {len(rows)} seasons ({rows[0]['season']}..{rows[-1]['season']})")


if __name__ == "__main__":
    run()
