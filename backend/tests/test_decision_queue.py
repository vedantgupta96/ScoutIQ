"""Tests for the decision-queue deep module and router.

Ordering/banding logic is tested directly against `_sort_key` and the individual item
builders with their DB collaborators monkeypatched — mirrors test_extension.py and
test_free_agency.py. The router is exercised with fakes.FakeDB for the team-not-found and
bad-season paths, and with `build_decision_queue` itself monkeypatched for the happy path.
"""
from fastapi.testclient import TestClient

from fakes import FakeDB

import scoutiq.api.decision_queue as dq
import scoutiq.api.routers.decision_queue as dqr
from scoutiq.api.cap import SeasonCapData
from scoutiq.api.deps import get_db
from scoutiq.api.extension import ExtensionDecision
from scoutiq.api.main import app
from scoutiq.model.roster_fit import RosterNeed, TeamFitProfile
from scoutiq.models import Contract, ContractYear, Player, Team

LAL_ID = 1610612747

CAPS = {
    "2025-26": SeasonCapData("2025-26", 154_647_000, 187_895_000, 195_945_000, 207_824_000),
}


def _client(fake_db):
    app.dependency_overrides[get_db] = lambda: fake_db
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def _item(*, priority="high", type_=dq.TYPE_OPTION, gap_pct=None, player_id=1, id_="z"):
    return dq.QueueItem(
        id=id_, type=type_, priority=priority, priority_reason="reason", title="t", detail="d",
        player_id=player_id, team_id=LAL_ID, value_pct=None, pay_pct=None, gap_pct=gap_pct,
        value_usd=None, pay_usd=None, destination="/players/1", season="2025-26", as_of="2025-26",
        caution=None,
    )


# --------------------------------------------------------------------------- ordering
def test_sort_key_orders_by_priority_band_first():
    high = _item(priority="high", id_="a")
    medium = _item(priority="medium", id_="b")
    low = _item(priority="low", id_="c")
    items = sorted([low, high, medium], key=dq._sort_key)
    assert [i.id for i in items] == ["a", "b", "c"]


def test_option_and_extension_outrank_cap_tier_in_same_band():
    # cap_tier can reach "high" (second apron); option/extension are also "high" but must
    # come first per the type-rank tiebreaker, regardless of insertion order.
    option = _item(priority="high", type_=dq.TYPE_OPTION, id_="option:1")
    extension = _item(priority="high", type_=dq.TYPE_EXTENSION, id_="extension:1")
    cap_tier = _item(priority="high", type_=dq.TYPE_CAP_TIER, player_id=None, id_="cap_tier:1")
    items = sorted([cap_tier, extension, option], key=dq._sort_key)
    assert [i.type for i in items] == [dq.TYPE_OPTION, dq.TYPE_EXTENSION, dq.TYPE_CAP_TIER]


def test_sort_key_orders_by_gap_pct_descending_with_none_last():
    small_gap = _item(priority="high", type_=dq.TYPE_OPTION, gap_pct=2.0, id_="a")
    big_gap = _item(priority="high", type_=dq.TYPE_OPTION, gap_pct=-9.0, id_="b")
    no_gap = _item(priority="high", type_=dq.TYPE_OPTION, gap_pct=None, id_="c")
    items = sorted([small_gap, no_gap, big_gap], key=dq._sort_key)
    assert [i.id for i in items] == ["b", "a", "c"]


def test_sort_key_player_id_ascending_with_none_last():
    team_level = _item(priority="low", type_=dq.TYPE_CAP_TIER, player_id=None, id_="cap_tier:1")
    player_level = _item(priority="low", type_=dq.TYPE_CAP_TIER, player_id=5, id_="cap_tier:2")

    # player-level (player_id=5) sorts before team-level (player_id=None) within the same
    # band+type+gap.
    ordered = sorted([team_level, player_level], key=dq._sort_key)
    assert [i.id for i in ordered] == ["cap_tier:2", "cap_tier:1"]


def test_sort_key_id_is_the_final_tiebreaker():
    tie_a = _item(priority="low", type_=dq.TYPE_ROSTER_NEED, player_id=None, id_="roster_need:a")
    tie_b = _item(priority="low", type_=dq.TYPE_ROSTER_NEED, player_id=None, id_="roster_need:b")

    # identical priority/type/gap/player_id (both team-level) -> id is the deciding tiebreaker.
    ordered = sorted([tie_b, tie_a], key=dq._sort_key)
    assert [i.id for i in ordered] == ["roster_need:a", "roster_need:b"]


def test_destinations_are_never_trade_routes():
    player = Player(player_id=1, full_name="Test Player", position="PG", current_team_id=LAL_ID)
    # No cap_pct/aav on the option year -> option_cap_pct is None -> the value lookup (which
    # would need a real db) is never reached; only .destination is under test here.
    final_year = ContractYear(contract_id=1, season="2025-26", cap_pct=None, aav=None, is_player_option=True)
    option = dq._option_item(None, player, LAL_ID, "2025-26", final_year, {})
    expiring = dq._expiring_item(player, LAL_ID, "2025-26", ContractYear(contract_id=1, season="2025-26", cap_pct=0.10))
    team = Team(team_id=LAL_ID, abbreviation="LAL", name="Los Angeles Lakers")

    destinations = [option.destination, expiring.destination, f"/players/{player.player_id}",
                    f"/teams/{team.team_id}", "/free-agency?tab=targets"]
    assert not any(d.startswith("/trade") for d in destinations)


# --------------------------------------------------------------------------- option / expiring
def test_option_item_high_band_with_verdict(monkeypatch):
    monkeypatch.setattr(dq, "_latest_value_pct", lambda db, player_id: 25.0)
    player = Player(player_id=1, full_name="Option Kid", position="PG", current_team_id=LAL_ID)
    final_year = ContractYear(contract_id=1, season="2025-26", cap_pct=0.10, is_player_option=True)

    item = dq._option_item(None, player, LAL_ID, "2025-26", final_year, dict(CAPS))

    assert item.priority == "high"
    assert item.type == dq.TYPE_OPTION
    assert item.priority_reason == "An option decision is pending for 2025-26."
    assert item.caution is None
    assert item.gap_pct == 15.0  # 25% value vs 10% option pay
    assert item.destination == "/free-agency?tab=options"


def test_option_item_missing_value_stays_high_band_with_caution(monkeypatch):
    monkeypatch.setattr(dq, "_latest_value_pct", lambda db, player_id: None)
    player = Player(player_id=1, full_name="Option Kid", position="PG", current_team_id=LAL_ID)
    final_year = ContractYear(contract_id=1, season="2025-26", cap_pct=0.10, is_team_option=True)

    item = dq._option_item(None, player, LAL_ID, "2025-26", final_year, dict(CAPS))

    assert item.priority == "high"  # factual, not valuation-dependent
    assert item.value_pct is None
    assert item.caution is not None


def test_option_item_missing_cap_data_omits_verdict():
    player = Player(player_id=1, full_name="Option Kid", position="PG", current_team_id=LAL_ID)
    final_year = ContractYear(contract_id=1, season="2025-26", cap_pct=None, aav=None, is_team_option=True)

    item = dq._option_item(None, player, LAL_ID, "2025-26", final_year, {})

    assert item.priority == "high"
    assert item.gap_pct is None
    assert item.value_pct is None
    assert "option decision pending" in item.title


def test_option_or_expiring_item_dispatches_on_option_flag(monkeypatch):
    monkeypatch.setattr(dq, "_latest_contract", lambda db, player_id: Contract(id=1, player_id=player_id, season_start="2023-24", years=1))
    monkeypatch.setattr(
        dq, "_contract_years",
        lambda db, contract_id: [ContractYear(contract_id=1, season="2025-26", cap_pct=0.12, is_team_option=True)],
    )
    monkeypatch.setattr(dq, "_latest_value_pct", lambda db, player_id: 20.0)
    player = Player(player_id=1, full_name="Kid", current_team_id=LAL_ID)
    item = dq._option_or_expiring_item(None, player, LAL_ID, "2025-26", {})
    assert item.type == dq.TYPE_OPTION


def test_option_or_expiring_item_expiring_when_not_option(monkeypatch):
    monkeypatch.setattr(dq, "_latest_contract", lambda db, player_id: Contract(id=1, player_id=player_id, season_start="2023-24", years=1))
    monkeypatch.setattr(
        dq, "_contract_years",
        lambda db, contract_id: [ContractYear(contract_id=1, season="2025-26", cap_pct=0.12)],
    )
    player = Player(player_id=1, full_name="Vet", current_team_id=LAL_ID)
    item = dq._option_or_expiring_item(None, player, LAL_ID, "2025-26", {})
    assert item.type == dq.TYPE_EXPIRING
    assert item.priority == "medium"
    assert item.priority_reason == "Final guaranteed year is 2025-26; reaches free agency after it."


def test_option_or_expiring_item_none_when_final_year_before_season(monkeypatch):
    monkeypatch.setattr(dq, "_latest_contract", lambda db, player_id: Contract(id=1, player_id=player_id, season_start="2023-24", years=1))
    monkeypatch.setattr(
        dq, "_contract_years",
        lambda db, contract_id: [ContractYear(contract_id=1, season="2024-25", cap_pct=0.12)],
    )
    player = Player(player_id=1, full_name="Gone", current_team_id=LAL_ID)
    assert dq._option_or_expiring_item(None, player, LAL_ID, "2025-26", {}) is None


def test_option_or_expiring_item_none_without_contract(monkeypatch):
    monkeypatch.setattr(dq, "_latest_contract", lambda db, player_id: None)
    player = Player(player_id=1, full_name="No Contract", current_team_id=LAL_ID)
    assert dq._option_or_expiring_item(None, player, LAL_ID, "2025-26", {}) is None


def test_expiring_item_uses_stored_cap_pct():
    player = Player(player_id=2, full_name="Vet Expiring")
    final_year = ContractYear(contract_id=1, season="2026-27", cap_pct=0.18, aav=20_000_000)
    item = dq._expiring_item(player, LAL_ID, "2026-27", final_year)
    assert item.pay_pct == 18.0
    assert item.pay_usd == 20_000_000
    assert item.destination == "/free-agency"


# --------------------------------------------------------------------------- extension
def _extension_decision(**overrides):
    base = dict(
        player_id=1, eligible=True, ineligible_reason=None, value_season="2025-26",
        value_pct=25.0, value_lo_pct=20.0, value_hi_pct=30.0, current_pay_pct=15.0,
        final_contract_season="2027-28", entering_season="2028-29",
        projected_aav_usd=30_000_000, projected_aav_lo_usd=24_000_000, projected_aav_hi_usd=36_000_000,
        projected_cap_usd=170_000_000, gap_pct=10.0, verdict="Extend now", tone="positive",
        rationale="Model value exceeds current pay.", trajectory_note=None, caveat="caveat",
    )
    base.update(overrides)
    return ExtensionDecision(**base)


def test_extension_item_extend_now_is_high_band(monkeypatch):
    monkeypatch.setattr(dq, "decide_extension", lambda db, pid: _extension_decision())
    player = Player(player_id=1, full_name="Star", current_team_id=LAL_ID)

    item = dq._extension_item(None, player, LAL_ID, "2025-26")

    assert item.priority == "high"
    assert item.destination == "/players/1"
    assert item.priority_reason == "Model value exceeds current pay."
    assert item.caution is None


def test_extension_item_no_model_value_forced_out_of_high_band(monkeypatch):
    """ADR-0001: a missing valuation must not produce a high-band valuation-dependent item."""
    monkeypatch.setattr(
        dq, "decide_extension",
        lambda db, pid: _extension_decision(verdict="No model value", tone="neutral", value_pct=None, gap_pct=None),
    )
    player = Player(player_id=1, full_name="Star", current_team_id=LAL_ID)

    item = dq._extension_item(None, player, LAL_ID, "2025-26")

    assert item.priority == "low"
    assert item.value_pct is None
    assert item.caution is not None


def test_extension_item_ineligible_omitted(monkeypatch):
    monkeypatch.setattr(dq, "decide_extension", lambda db, pid: _extension_decision(eligible=False, verdict="Not extension-eligible"))
    player = Player(player_id=1, full_name="Impending FA", current_team_id=LAL_ID)
    assert dq._extension_item(None, player, LAL_ID, "2025-26") is None


def test_extension_item_lookup_error_omitted(monkeypatch):
    monkeypatch.setattr(dq, "decide_extension", lambda db, pid: (_ for _ in ()).throw(LookupError("no contract")))
    player = Player(player_id=1, full_name="No Contract", current_team_id=LAL_ID)
    assert dq._extension_item(None, player, LAL_ID, "2025-26") is None


def test_extension_item_missing_model_artifact_omitted(monkeypatch):
    """A globally missing model artifact must degrade this one item, not 500 the queue."""
    monkeypatch.setattr(dq, "decide_extension", lambda db, pid: (_ for _ in ()).throw(FileNotFoundError("model missing")))
    player = Player(player_id=1, full_name="No Model", current_team_id=LAL_ID)
    assert dq._extension_item(None, player, LAL_ID, "2025-26") is None


def test_extension_item_fair_is_medium_and_dont_extend_is_low(monkeypatch):
    monkeypatch.setattr(dq, "decide_extension", lambda db, pid: _extension_decision(verdict="Fair — extend at market or wait", tone="neutral"))
    player = Player(player_id=1, full_name="Fair Player", current_team_id=LAL_ID)
    assert dq._extension_item(None, player, LAL_ID, "2025-26").priority == "medium"

    monkeypatch.setattr(dq, "decide_extension", lambda db, pid: _extension_decision(verdict="Don't extend", tone="negative"))
    player2 = Player(player_id=2, full_name="Overpaid Player", current_team_id=LAL_ID)
    assert dq._extension_item(None, player2, LAL_ID, "2025-26").priority == "low"


# --------------------------------------------------------------------------- cap tier
def _team():
    return Team(team_id=LAL_ID, abbreviation="LAL", name="Los Angeles Lakers")


def test_cap_tier_band_mapping(monkeypatch):
    caps = dict(CAPS)
    roster = [Player(player_id=1, current_team_id=LAL_ID)]
    team = _team()

    monkeypatch.setattr(dq, "team_cap_hits", lambda db, ids, season: ({1: 100_000_000}, {}))
    below_tax = dq._cap_tier_item(None, team, LAL_ID, "2025-26", roster, caps)
    assert below_tax.priority == "low"

    monkeypatch.setattr(dq, "team_cap_hits", lambda db, ids, season: ({1: 190_000_000}, {}))
    taxpayer = dq._cap_tier_item(None, team, LAL_ID, "2025-26", roster, caps)
    assert taxpayer.priority == "medium"

    monkeypatch.setattr(dq, "team_cap_hits", lambda db, ids, season: ({1: 197_000_000}, {}))
    first_apron = dq._cap_tier_item(None, team, LAL_ID, "2025-26", roster, caps)
    assert first_apron.priority == "medium"

    monkeypatch.setattr(dq, "team_cap_hits", lambda db, ids, season: ({1: 210_000_000}, {}))
    second_apron = dq._cap_tier_item(None, team, LAL_ID, "2025-26", roster, caps)
    assert second_apron.priority == "high"
    assert "second apron" in second_apron.priority_reason


def test_cap_tier_item_always_appears_without_valuation(monkeypatch):
    """Factual contract/cap item: survives even though it never touches the valuation model."""
    caps = dict(CAPS)
    roster: list[Player] = []
    team = _team()
    monkeypatch.setattr(dq, "team_cap_hits", lambda db, ids, season: ({}, {}))

    item = dq._cap_tier_item(None, team, LAL_ID, "2025-26", roster, caps)

    assert item.type == dq.TYPE_CAP_TIER
    assert item.priority == "low"
    assert item.pay_usd == 0


def test_cap_tier_item_missing_cap_constants_has_caution(monkeypatch):
    roster = [Player(player_id=1, current_team_id=LAL_ID)]
    team = _team()
    monkeypatch.setattr(dq, "team_cap_hits", lambda db, ids, season: ({1: 50_000_000}, {}))

    item = dq._cap_tier_item(None, team, LAL_ID, "2025-26", roster, {})

    assert item.caution is not None
    assert item.priority == "low"  # classify_tier defaults to below-tax without a tax line


# --------------------------------------------------------------------------- roster need
def test_roster_need_critical_is_medium_and_need_is_low(monkeypatch):
    monkeypatch.setattr(dq, "load_fit_context", lambda db, season: object())
    roster = [Player(player_id=1, current_team_id=LAL_ID)]

    critical_need = RosterNeed(key="spacing", label="Spacing", coverage_pct=40.0, deficit_pct=60.0, status="critical", caution=None)
    monkeypatch.setattr(dq, "profile_roster", lambda context, ids: TeamFitProfile(
        roster_player_count=1, profiled_player_count=1, confidence="medium", needs=[critical_need],
    ))
    item = dq._roster_need_item(None, LAL_ID, roster, "2025-26")
    assert item.priority == "medium"
    assert item.destination == "/free-agency?tab=targets"
    assert item.as_of == dq.LATEST_SEASON

    lesser_need = RosterNeed(key="defense", label="Defensive activity", coverage_pct=85.0, deficit_pct=15.0, status="need", caution="noisy metric")
    monkeypatch.setattr(dq, "profile_roster", lambda context, ids: TeamFitProfile(
        roster_player_count=1, profiled_player_count=1, confidence="medium", needs=[lesser_need],
    ))
    item = dq._roster_need_item(None, LAL_ID, roster, "2025-26")
    assert item.priority == "low"
    assert item.caution == "noisy metric"


def test_roster_need_covered_omitted(monkeypatch):
    monkeypatch.setattr(dq, "load_fit_context", lambda db, season: object())
    covered = RosterNeed(key="scoring", label="Scoring", coverage_pct=99.0, deficit_pct=1.0, status="covered", caution=None)
    monkeypatch.setattr(dq, "profile_roster", lambda context, ids: TeamFitProfile(
        roster_player_count=1, profiled_player_count=1, confidence="high", needs=[covered],
    ))
    roster = [Player(player_id=1, current_team_id=LAL_ID)]
    assert dq._roster_need_item(None, LAL_ID, roster, "2025-26") is None


def test_roster_need_empty_roster_omitted():
    assert dq._roster_need_item(None, LAL_ID, [], "2025-26") is None


# --------------------------------------------------------------------------- build_decision_queue
def test_build_decision_queue_unknown_team_raises_lookup_error():
    db = FakeDB(teams=[])
    try:
        dq.build_decision_queue(db, LAL_ID)
        assert False, "expected LookupError"
    except LookupError:
        pass


def test_build_decision_queue_assembles_and_sorts(monkeypatch):
    team = _team()
    p1 = Player(player_id=1, full_name="Rostered One", current_team_id=LAL_ID)
    p2 = Player(player_id=2, full_name="Rostered Two", current_team_id=LAL_ID)
    db = FakeDB(teams=[team], players=[p1, p2])

    monkeypatch.setattr(dq, "load_season_caps", lambda db: dict(CAPS))

    monkeypatch.setattr(
        dq, "_player_items",
        lambda db, player, team_id, season, caps: (
            [_item(priority="high", type_=dq.TYPE_OPTION, player_id=player.player_id, id_=f"option:{player.player_id}")]
            if player.player_id == 1
            else [_item(priority="low", type_=dq.TYPE_EXTENSION, player_id=player.player_id, id_=f"extension:{player.player_id}")]
        ),
    )
    monkeypatch.setattr(
        dq, "_cap_tier_item",
        lambda db, team, team_id, season, roster, caps: _item(priority="medium", type_=dq.TYPE_CAP_TIER, player_id=None, id_="cap_tier:team"),
    )
    monkeypatch.setattr(dq, "_roster_need_item", lambda db, team_id, roster, season: None)

    queue = dq.build_decision_queue(db, LAL_ID)

    assert queue.team_id == LAL_ID
    assert queue.team_name == "Los Angeles Lakers"
    assert queue.season == dq.LATEST_SEASON
    assert queue.generated_from == "latest"
    assert [i.id for i in queue.items] == ["option:1", "cap_tier:team", "extension:2"]


def test_build_decision_queue_generated_from_non_latest_season(monkeypatch):
    team = _team()
    db = FakeDB(teams=[team], players=[])
    monkeypatch.setattr(dq, "load_season_caps", lambda db: dict(CAPS))
    monkeypatch.setattr(
        dq, "_cap_tier_item",
        lambda db, team, team_id, season, roster, caps: _item(priority="low", type_=dq.TYPE_CAP_TIER, player_id=None, id_="cap_tier:team"),
    )
    monkeypatch.setattr(dq, "_roster_need_item", lambda db, team_id, roster, season: None)

    queue = dq.build_decision_queue(db, LAL_ID, "2026-27")

    assert queue.season == "2026-27"
    assert queue.generated_from == "2026-27"


# --------------------------------------------------------------------------- router
def test_router_unknown_team_404():
    db = FakeDB(teams=[])
    resp = _client(db).get("/decision-queue", params={"team_id": LAL_ID})
    assert resp.status_code == 404


def test_router_bad_season_422():
    db = FakeDB(teams=[_team()])
    resp = _client(db).get("/decision-queue", params={"team_id": LAL_ID, "season": "20xx"})
    assert resp.status_code == 422


def test_router_happy_path(monkeypatch):
    canned = dq.DecisionQueue(
        team_id=LAL_ID, team_name="Los Angeles Lakers", season="2025-26", generated_from="latest",
        items=[_item(priority="high", type_=dq.TYPE_CAP_TIER, player_id=None, id_="cap_tier:team")],
        caveat="caveat text",
    )
    monkeypatch.setattr(dqr, "build_decision_queue", lambda db, team_id, season: canned)

    resp = _client(FakeDB()).get("/decision-queue", params={"team_id": LAL_ID})

    assert resp.status_code == 200
    body = resp.json()
    assert body["team_id"] == LAL_ID
    assert body["team_name"] == "Los Angeles Lakers"
    assert body["items"][0]["id"] == "cap_tier:team"
    assert not any(item["destination"].startswith("/trade") for item in body["items"])
