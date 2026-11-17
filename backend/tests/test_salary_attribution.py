import json

import pytest

from scoutiq.etl.salary_attribution import (
    ATTRIBUTED,
    RULE_VERSION,
    UNRESOLVED,
    UNRESOLVED_REASONS,
    SigningFacts,
    attribute_salary,
)
from scoutiq.sources.contract_events import SalaryRow

SEASON = "2019-20"
M = 1_000_000


def _facts(**kw) -> SigningFacts:
    base = dict(
        event_key="1:2019-07-01:standard:riverton-owls",
        team="Riverton Owls",
        first_paid_season=SEASON,
        entry_combines_forms=False,
        team_signings_in_season=1,
        prior_terminations_by_team=0,
        prior_service_with_team=0,
        prior_releases_team_unknown=0,
        in_season=False,
    )
    base.update(kw)
    return SigningFacts(**base)


OWLS = SalaryRow(SEASON, "Riverton Owls", 3 * M)
FOXES = SalaryRow(SEASON, "Springfield Foxes", 2 * M)


def test_attributed_single_row():
    att = attribute_salary(_facts(), [OWLS])
    assert (att.status, att.reason, att.row_index, att.salary) == (ATTRIBUTED, None, 0, 3 * M)
    assert att.evidence["rule"] == "single_row_single_signing"
    assert RULE_VERSION == "v1"


def test_multi_team_season_uses_only_signing_team_row_never_summed():
    att = attribute_salary(_facts(), [FOXES, OWLS])
    assert (att.status, att.row_index, att.salary) == (ATTRIBUTED, 1, 3 * M)
    assert att.salary != OWLS.salary + FOXES.salary
    assert att.evidence["multi_team_season"] is True
    assert att.evidence["season_row_teams"] == ["Springfield Foxes", "Riverton Owls"]
    assert att.evidence["signing_team_row_count"] == 1


def test_duplicate_same_team_rows_unresolved():
    att = attribute_salary(_facts(), [OWLS, SalaryRow(SEASON, "Riverton Owls", 1 * M)])
    assert (att.status, att.reason, att.row_index, att.salary) == (UNRESOLVED, "multiple_rows_for_signing_team", None, None)
    assert att.evidence["signing_team_row_count"] == 2
    assert att.evidence["season_row_teams"] == ["Riverton Owls"]


@pytest.mark.parametrize(
    "facts, rows, reason",
    [
        (dict(team=None), [OWLS], "signing_team_unknown"),
        ({}, [], "no_salary_rows_for_season"),
        ({}, [FOXES], "no_row_for_signing_team"),
        ({}, [OWLS, OWLS], "multiple_rows_for_signing_team"),
        (dict(team_signings_in_season=2), [OWLS], "multiple_signings_with_team"),
        (dict(entry_combines_forms=True), [OWLS], "entry_combines_forms"),
        (dict(prior_terminations_by_team=1), [OWLS], "earlier_termination_by_signing_team"),
        (dict(prior_service_with_team=1), [OWLS], "earlier_service_with_signing_team"),
        (dict(prior_releases_team_unknown=1), [OWLS], "earlier_release_team_unknown"),
    ],
)
def test_each_unresolved_reason(facts, rows, reason):
    att = attribute_salary(_facts(**facts), rows)
    assert (att.status, att.reason) == (UNRESOLVED, reason)
    assert att.evidence["rule"] is None


def test_reason_constants_in_documented_order():
    assert UNRESOLVED_REASONS == (
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


def test_precedence_first_match_wins():
    everything_wrong = _facts(
        entry_combines_forms=True,
        team_signings_in_season=2,
        prior_terminations_by_team=1,
        prior_releases_team_unknown=1,
    )
    assert attribute_salary(everything_wrong, [OWLS]).reason == "multiple_signings_with_team"
    no_signings = _facts(
        entry_combines_forms=True, prior_terminations_by_team=1, prior_releases_team_unknown=1
    )
    assert attribute_salary(no_signings, [OWLS]).reason == "entry_combines_forms"
    assert attribute_salary(_facts(prior_terminations_by_team=1, prior_releases_team_unknown=1), [OWLS]).reason == (
        "earlier_termination_by_signing_team"
    )
    assert attribute_salary(
        _facts(prior_service_with_team=1, prior_releases_team_unknown=1), [OWLS]
    ).reason == "earlier_service_with_signing_team"
    assert attribute_salary(
        _facts(prior_terminations_by_team=1, prior_service_with_team=1), [OWLS]
    ).reason == "earlier_termination_by_signing_team"
    assert attribute_salary(_facts(team=None, entry_combines_forms=True), []).reason == "signing_team_unknown"
    assert attribute_salary(_facts(team_signings_in_season=3), [FOXES]).reason == "no_row_for_signing_team"


@pytest.mark.parametrize("in_season", [True, False])
def test_in_season_flag_carried_in_evidence(in_season):
    att = attribute_salary(_facts(in_season=in_season), [OWLS])
    assert att.status == ATTRIBUTED
    assert att.evidence["in_season"] is in_season


def test_evidence_is_json_serializable_with_stable_keys():
    att = attribute_salary(_facts(prior_terminations_by_team=2), [FOXES, OWLS])
    json.dumps(att.evidence)
    assert list(att.evidence) == [
        "rule",
        "season_row_count",
        "season_row_teams",
        "signing_team_row_count",
        "team_signings_in_season",
        "prior_terminations_by_team",
        "prior_service_with_team",
        "prior_releases_team_unknown",
        "in_season",
        "multi_team_season",
    ]
    assert att.evidence["prior_terminations_by_team"] == 2
    assert att.evidence["season_row_count"] == 2
