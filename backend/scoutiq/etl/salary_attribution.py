"""Pure rule for attributing one per-team salary row to a contract decision (SCO-44).

No DB, no I/O. A decision is attributed only when the signing team has exactly one salary row in
the first paid season and nothing else in the transaction history makes that row ambiguous. Row
sums are never used: a season total is not a decision salary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from scoutiq.sources.contract_events import SalaryRow

RULE_VERSION = "v1"
ATTRIBUTED, UNRESOLVED = "attributed", "unresolved"
UNRESOLVED_REASONS = (
    "signing_team_unknown",
    "no_salary_rows_for_season",
    "no_row_for_signing_team",
    "multiple_rows_for_signing_team",
    "multiple_signings_with_team",
    "entry_combines_forms",
    "earlier_termination_by_signing_team",
    "earlier_service_with_signing_team",
    "earlier_release_team_unknown",
)


@dataclass(frozen=True)
class SigningFacts:
    event_key: str
    team: str | None
    first_paid_season: str
    entry_combines_forms: bool
    team_signings_in_season: int
    prior_terminations_by_team: int
    prior_service_with_team: int
    prior_releases_team_unknown: int
    in_season: bool


@dataclass(frozen=True)
class Attribution:
    status: str
    reason: str | None
    row_index: int | None
    salary: int | None
    evidence: dict


def attribute_salary(facts: SigningFacts, season_rows: Sequence[SalaryRow]) -> Attribution:
    team_rows = [i for i, r in enumerate(season_rows) if facts.team is not None and r.team == facts.team]
    reason: str | None = None
    if facts.team is None:
        reason = "signing_team_unknown"
    elif not season_rows:
        reason = "no_salary_rows_for_season"
    elif not team_rows:
        reason = "no_row_for_signing_team"
    elif len(team_rows) >= 2:
        reason = "multiple_rows_for_signing_team"
    elif facts.team_signings_in_season != 1:
        reason = "multiple_signings_with_team"
    elif facts.entry_combines_forms:
        reason = "entry_combines_forms"
    elif facts.prior_terminations_by_team > 0:
        reason = "earlier_termination_by_signing_team"
    elif facts.prior_service_with_team > 0:
        reason = "earlier_service_with_signing_team"
    elif facts.prior_releases_team_unknown > 0:
        reason = "earlier_release_team_unknown"

    attributed = reason is None
    evidence = {
        "rule": "single_row_single_signing" if attributed else None,
        "season_row_count": len(season_rows),
        "season_row_teams": list(dict.fromkeys(r.team for r in season_rows)),
        "signing_team_row_count": len(team_rows),
        "team_signings_in_season": facts.team_signings_in_season,
        "entry_combines_forms": facts.entry_combines_forms,
        "prior_terminations_by_team": facts.prior_terminations_by_team,
        "prior_service_with_team": facts.prior_service_with_team,
        "prior_releases_team_unknown": facts.prior_releases_team_unknown,
        "in_season": facts.in_season,
        "multi_team_season": len(season_rows) >= 2,
    }
    if not attributed:
        return Attribution(UNRESOLVED, reason, None, None, evidence)
    index = team_rows[0]
    return Attribution(ATTRIBUTED, None, index, season_rows[index].salary, evidence)
