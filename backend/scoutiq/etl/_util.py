"""Shared ETL helpers."""
from __future__ import annotations

import math
from typing import Any


def clean(v: Any) -> Any:
    """Make a pandas/numpy cell JSON- and DB-safe: NaN -> None, numpy scalar -> python scalar."""
    if v is None:
        return None
    item = v.item() if hasattr(v, "item") else v
    if isinstance(item, float) and math.isnan(item):
        return None
    return item


def jsonify(row, keys: list[str]) -> dict:
    """Pull `keys` from a pandas row into a clean dict, dropping missing/NaN values."""
    out = {}
    for k in keys:
        if k in row:
            cv = clean(row[k])
            if cv is not None:
                out[k] = cv
    return out
