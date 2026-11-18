"""Guarantee semantics for stored contract years: None is unknown, False is confirmed non-guaranteed."""
from __future__ import annotations

from typing import Iterable, Literal

GuaranteeStatus = Literal["known", "unknown", "partial_unknown"]


def guarantee_status(flags: Iterable[bool | None]) -> GuaranteeStatus:
    values = list(flags)
    unknown = sum(1 for f in values if f is None)
    if values and unknown == len(values):
        return "unknown"
    return "partial_unknown" if unknown else "known"
