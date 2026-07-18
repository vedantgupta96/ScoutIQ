"""One in-memory fake DB session for router/module tests.

The seam under test is SQLAlchemy's `Session`: `get`, `scalars`, `execute`. Rather
than each test file re-rolling a result wrapper and a `str(stmt)` dispatch, they
configure this one fake with the row-sets their queries should return.

`scalars()` dispatches on the queried table name, in a fixed priority order (so a
more specific match like `player_salaries` wins over a bare table). Queries that
select column tuples or join across tables (e.g. the batched summaries and
latest-stats-row lookups) encode a specific column shape a generic fake can't
guess — pass `on_execute` / `on_scalars` for those; the hook is consulted first
and returning None falls through to the table dispatch.
"""
from __future__ import annotations

from collections.abc import Callable

from scoutiq.models import CapConstants, Player, Team


class FakeScalarResult:
    def __init__(self, values):
        self.values = list(values)

    def all(self):
        return self.values

    def first(self):
        return self.values[0] if self.values else None


# str(stmt) substring -> the row-set kwarg it should return, most specific first.
_TABLE_DISPATCH: list[tuple[str, str]] = [
    ("cap_constants", "caps"),
    ("player_salaries", "salaries"),
    ("free_agent_rights", "rights"),
    ("contract_years", "contract_years"),
    ("FROM contracts", "contracts"),
    ("FROM players", "players"),
    ("FROM teams", "teams"),
    ("player_seasons", "seasons"),
]

# model -> primary-key attribute, for get().
_PK = {Player: "player_id", Team: "team_id", CapConstants: "season"}


class FakeDB:
    """A configurable stand-in for a SQLAlchemy Session.

    Pass the row-sets the test's queries should see (players=, seasons=, caps=…).
    `on_scalars` / `on_execute` take str(stmt) and return rows to override the
    table dispatch, or None to fall through.
    """

    def __init__(
        self,
        *,
        players=(),
        seasons=(),
        salaries=(),
        caps=(),
        contracts=(),
        contract_years=(),
        teams=(),
        rights=(),
        on_scalars: Callable[[str], list | None] | None = None,
        on_execute: Callable[[str], list | None] | None = None,
    ):
        self.players = list(players)
        self.seasons = list(seasons)
        self.salaries = list(salaries)
        self.caps = list(caps)
        self.contracts = list(contracts)
        self.contract_years = list(contract_years)
        self.teams = list(teams)
        self.rights = list(rights)
        self._on_scalars = on_scalars
        self._on_execute = on_execute

    def get(self, model, key):
        rows = getattr(self, {Player: "players", Team: "teams", CapConstants: "caps"}.get(model, ""), [])
        pk = _PK.get(model)
        if pk is None:
            return None
        return next((row for row in rows if getattr(row, pk) == key), None)

    def scalars(self, stmt):
        sql = str(stmt)
        if self._on_scalars is not None:
            rows = self._on_scalars(sql)
            if rows is not None:
                return FakeScalarResult(rows)
        for needle, attr in _TABLE_DISPATCH:
            if needle in sql:
                return FakeScalarResult(getattr(self, attr))
        return FakeScalarResult([])

    def execute(self, stmt):
        sql = str(stmt)
        if self._on_execute is not None:
            rows = self._on_execute(sql)
            if rows is not None:
                return FakeScalarResult(rows)
        return FakeScalarResult([])
