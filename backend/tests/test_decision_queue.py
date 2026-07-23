"""Tests for the decision-queue deep module and router.

Ordering/banding logic is tested directly against `_sort_key` and the individual item
builders with their DB collaborators monkeypatched — mirrors test_extension.py and
test_free_agency.py. The router is exercised with fakes.FakeDB for the team-not-found and
bad-season paths, and with `build_decision_queue` itself monkeypatched for the happy path.
"""
from fastapi.testclient import TestClient

from fakes import FakeDB

import scoutiq.api.decision_queue as dq
import scoutiq.api.extension as ext_module
import scoutiq.api.routers.decision_queue as dqr
from scoutiq.api.cap import SeasonCapData
from scoutiq.api.deps import get_db
from scoutiq.api.extension import ExtensionSummary
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


def _ctx(**overrides):
    base_caps = overrides.pop("caps", dict(CAPS))
    cap_row = base_caps.get("2025-26")
    base = dict(
        season="2025-26",
        caps=base_caps,
        salary_cap=cap_row.salary_cap if cap_row else None,
        tax_line=cap_row.tax_line if cap_row else None,
        first_apron=cap_row.first_apron if cap_row else None,
        second_apron=cap_row.second_apron if cap_row else None,
        contracts_by_player={},
        years_by_contract={},
        value_pct_by_player={},
        option_pool_entering_by_player={},
        cap_hits={},
        extension_summaries={},
    )
    base.update(overrides)
    return dq._QueueContext(**base)


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


def test_destinations_are_never_trade_routes(monkeypatch):
    player = Player(player_id=1, full_name="Test Player", position="PG", current_team_id=LAL_ID)
    # No cap_pct on the option year -> option_cap_pct is None -> no verdict is computed;
    # only .destination is under test here.
    final_year = ContractYear(contract_id=1, season="2025-26", cap_pct=None, aav=None, is_player_option=True)
    option = dq._option_item(player, LAL_ID, final_year, "2026-27", _ctx(), None)
    expiring = dq._expiring_item(
        player, LAL_ID, ContractYear(contract_id=1, season="2025-26", cap_pct=0.10), _ctx(),
    )

    cap_tier = dq._cap_tier_item(_team(), LAL_ID, [], _ctx())

    monkeypatch.setattr(dq, "load_fit_context", lambda db, season: object())
    need = RosterNeed(key="spacing", label="Spacing", coverage_pct=40.0, deficit_pct=60.0, status="need", caution=None)
    monkeypatch.setattr(dq, "profile_roster", lambda context, ids: TeamFitProfile(
        roster_player_count=1, profiled_player_count=1, confidence="medium", needs=[need],
    ))
    roster_need = dq._roster_need_item(None, LAL_ID, [player], "2025-26")

    destinations = [
        option.destination, expiring.destination, f"/players/{player.player_id}",
        cap_tier.destination, roster_need.destination,
    ]
    assert not any(d.startswith("/trade") for d in destinations)
    assert cap_tier.destination == f"/teams?team={LAL_ID}"
    assert roster_need.destination == f"/free-agency?tab=targets&team={LAL_ID}"


# --------------------------------------------------------------------------- option / expiring
def test_option_item_high_band_with_verdict():
    player = Player(player_id=1, full_name="Option Kid", position="PG", current_team_id=LAL_ID)
    final_year = ContractYear(contract_id=1, season="2025-26", cap_pct=0.10, is_player_option=True)

    item = dq._option_item(player, LAL_ID, final_year, "2026-27", _ctx(), 25.0)

    assert item.priority == "high"
    assert item.type == dq.TYPE_OPTION
    assert item.priority_reason == "An option decision is pending for the 2026-27 offseason."
    assert item.caution is None
    assert item.gap_pct == 15.0  # 25% value vs 10% option pay
    assert item.destination == "/free-agency?tab=options"


def test_option_item_as_of_is_the_option_year_not_the_queue_season():
    """B2: the option's salary belongs to the option year, which can be well past the queue's
    current season; `as_of` must track it, while `season` stays the queue's own context."""
    player = Player(player_id=1, full_name="Option Kid", position="PG", current_team_id=LAL_ID)
    final_year = ContractYear(contract_id=1, season="2026-27", cap_pct=0.10, is_player_option=True)

    item = dq._option_item(player, LAL_ID, final_year, "2027-28", _ctx(), 25.0)

    assert item.season == "2025-26"
    assert item.as_of == "2026-27"
    assert item.priority_reason == "An option decision is pending for the 2027-28 offseason."


def test_option_item_missing_value_stays_high_band_with_caution():
    player = Player(player_id=1, full_name="Option Kid", position="PG", current_team_id=LAL_ID)
    final_year = ContractYear(contract_id=1, season="2025-26", cap_pct=0.10, is_team_option=True)

    item = dq._option_item(player, LAL_ID, final_year, "2026-27", _ctx(), None)

    assert item.priority == "high"  # factual, not valuation-dependent
    assert item.value_pct is None
    assert item.caution is not None


def test_option_item_missing_cap_data_omits_verdict():
    player = Player(player_id=1, full_name="Option Kid", position="PG", current_team_id=LAL_ID)
    final_year = ContractYear(contract_id=1, season="2025-26", cap_pct=None, aav=None, is_team_option=True)

    item = dq._option_item(player, LAL_ID, final_year, "2026-27", _ctx(caps={}), None)

    assert item.priority == "high"
    assert item.gap_pct is None
    assert item.value_pct is None
    assert "option decision pending" in item.title


def test_option_or_expiring_item_option_pool_member_produces_option_item():
    """F3: pool membership drives the dispatch, not the option flag alone."""
    player = Player(player_id=1, full_name="Kid", current_team_id=LAL_ID)
    contract = Contract(id=10, player_id=1, season_start="2023-24", years=1)
    years = [ContractYear(contract_id=10, season="2025-26", cap_pct=0.12, is_team_option=True)]

    ctx = _ctx(
        contracts_by_player={1: contract}, years_by_contract={10: years},
        value_pct_by_player={1: 20.0}, option_pool_entering_by_player={1: "2026-27"},
    )
    item = dq._option_or_expiring_item(player, LAL_ID, ctx)

    assert item.type == dq.TYPE_OPTION


def test_option_or_expiring_item_expiring_when_not_in_option_pool():
    player = Player(player_id=1, full_name="Vet", current_team_id=LAL_ID)
    contract = Contract(id=10, player_id=1, season_start="2023-24", years=1)
    years = [ContractYear(contract_id=10, season="2025-26", cap_pct=0.12)]

    ctx = _ctx(contracts_by_player={1: contract}, years_by_contract={10: years})
    item = dq._option_or_expiring_item(player, LAL_ID, ctx)

    assert item.type == dq.TYPE_EXPIRING
    assert item.priority == "medium"
    assert item.priority_reason == "Final guaranteed year is 2025-26; reaches free agency after it."


def test_option_or_expiring_item_future_option_not_in_pool_produces_no_item():
    """F3: an option flagged several seasons out isn't in the current entering-season Free
    Agency options pool, so it isn't "pending" yet and produces no item at all."""
    player = Player(player_id=1, full_name="Gone Later", current_team_id=LAL_ID)
    contract = Contract(id=10, player_id=1, season_start="2023-24", years=6)
    years = [ContractYear(contract_id=10, season="2028-29", cap_pct=0.15, is_player_option=True)]

    ctx = _ctx(contracts_by_player={1: contract}, years_by_contract={10: years})
    item = dq._option_or_expiring_item(player, LAL_ID, ctx)

    assert item is None


def test_option_or_expiring_item_none_when_final_year_before_season():
    player = Player(player_id=1, full_name="Gone", current_team_id=LAL_ID)
    contract = Contract(id=10, player_id=1, season_start="2022-23", years=2)
    years = [ContractYear(contract_id=10, season="2024-25", cap_pct=0.12)]

    ctx = _ctx(contracts_by_player={1: contract}, years_by_contract={10: years})
    item = dq._option_or_expiring_item(player, LAL_ID, ctx)

    assert item is None


def test_current_option_pool_entering_filters_to_option_types(monkeypatch):
    class _Entry:
        def __init__(self, player_id, fa_type, entering_season):
            self.player = Player(player_id=player_id)
            self.fa_type = fa_type
            self.entering_season = entering_season

    monkeypatch.setattr(dq.fa_router, "_resolve_entering", lambda season: "2026-27")
    monkeypatch.setattr(
        dq.fa_router, "_assemble_pool",
        lambda db, entering, **kw: [
            _Entry(1, dq.fa.FA_PLAYER_OPTION, "2026-27"),
            _Entry(2, dq.fa.FA_TEAM_OPTION, "2026-27"),
            _Entry(3, dq.fa.FA_EXPIRING, "2026-27"),
        ],
    )
    assert dq._current_option_pool_entering(None) == {1: "2026-27", 2: "2026-27"}


def test_option_or_expiring_item_none_without_contract():
    player = Player(player_id=1, full_name="No Contract", current_team_id=LAL_ID)
    assert dq._option_or_expiring_item(player, LAL_ID, _ctx()) is None


def test_expiring_item_uses_stored_cap_pct():
    player = Player(player_id=2, full_name="Vet Expiring")
    final_year = ContractYear(contract_id=1, season="2026-27", cap_pct=0.18, aav=20_000_000)
    item = dq._expiring_item(player, LAL_ID, final_year, _ctx(season="2026-27"))
    assert item.pay_pct == 18.0
    assert item.pay_usd == 20_000_000
    assert item.destination == "/free-agency"


def test_expiring_item_derives_pay_pct_from_cap_hit_when_cap_pct_missing():
    player = Player(player_id=3, full_name="No Stored Pct")
    final_year = ContractYear(contract_id=1, season="2026-27", cap_pct=None, aav=None)
    caps = {"2026-27": SeasonCapData("2026-27", 165_000_000, 200_000_000, 210_000_000, 220_000_000)}
    ctx = _ctx(season="2026-27", caps=caps, cap_hits={3: 16_500_000})

    item = dq._expiring_item(player, LAL_ID, final_year, ctx)

    assert item.pay_pct == 10.0


# --------------------------------------------------------------------------- extension
def test_extension_item_extend_now_is_high_band():
    player = Player(player_id=1, full_name="Star", current_team_id=LAL_ID)
    summary = ExtensionSummary(
        player_id=1, eligible=True, has_model_value=True, value_pct=25.0, current_pay_pct=15.0,
        gap_pct=10.0, verdict="Extend now", tone="positive", final_contract_season="2027-28",
    )
    ctx = _ctx(extension_summaries={1: summary})

    item = dq._extension_item(player, LAL_ID, ctx)

    assert item.priority == "high"
    assert item.destination == "/players/1"
    assert "extending now locks in below-market cost" in item.priority_reason
    assert item.caution is None


def test_extension_item_no_model_value_is_low_band_with_caution():
    """ADR-0001: a missing valuation must not produce a high-band valuation-dependent item;
    it degrades to a low-priority contract fact with an explanatory caution."""
    player = Player(player_id=1, full_name="Star", current_team_id=LAL_ID)
    summary = ExtensionSummary(
        player_id=1, eligible=True, has_model_value=False, value_pct=None, current_pay_pct=15.0,
        gap_pct=None, verdict=None, tone=None, final_contract_season="2027-28",
    )
    ctx = _ctx(extension_summaries={1: summary})

    item = dq._extension_item(player, LAL_ID, ctx)

    assert item.priority == "low"
    assert item.value_pct is None
    assert item.pay_pct == 15.0
    assert item.caution is not None


def test_extension_item_ineligible_omitted():
    player = Player(player_id=1, full_name="Impending FA", current_team_id=LAL_ID)
    summary = ExtensionSummary(
        player_id=1, eligible=False, has_model_value=False, value_pct=None, current_pay_pct=None,
        gap_pct=None, verdict=None, tone=None, final_contract_season="2025-26",
    )
    ctx = _ctx(extension_summaries={1: summary})
    assert dq._extension_item(player, LAL_ID, ctx) is None


def test_extension_item_missing_summary_omitted():
    """No contract/eligibility data at all for this player (e.g. no contract row) -> omitted,
    same as the ineligible case."""
    player = Player(player_id=1, full_name="No Contract", current_team_id=LAL_ID)
    assert dq._extension_item(player, LAL_ID, _ctx()) is None


def test_extension_item_fair_is_medium_and_dont_extend_is_low():
    player = Player(player_id=1, full_name="Fair Player", current_team_id=LAL_ID)
    summary = ExtensionSummary(
        player_id=1, eligible=True, has_model_value=True, value_pct=20.4, current_pay_pct=20.0,
        gap_pct=0.4, verdict="Fair — extend at market or wait", tone="neutral", final_contract_season="2027-28",
    )
    ctx = _ctx(extension_summaries={1: summary})
    assert dq._extension_item(player, LAL_ID, ctx).priority == "medium"

    player2 = Player(player_id=2, full_name="Overpaid Player", current_team_id=LAL_ID)
    summary2 = ExtensionSummary(
        player_id=2, eligible=True, has_model_value=True, value_pct=10.0, current_pay_pct=20.0,
        gap_pct=-10.0, verdict="Don't extend", tone="negative", final_contract_season="2027-28",
    )
    ctx2 = _ctx(extension_summaries={2: summary2})
    assert dq._extension_item(player2, LAL_ID, ctx2).priority == "low"


# --------------------------------------------------------------------------- cap tier
def _team():
    return Team(team_id=LAL_ID, abbreviation="LAL", name="Los Angeles Lakers")


def test_cap_tier_band_mapping():
    roster = [Player(player_id=1, current_team_id=LAL_ID)]
    team = _team()

    below_tax = dq._cap_tier_item(team, LAL_ID, roster, _ctx(cap_hits={1: 100_000_000}))
    assert below_tax.priority == "low"

    taxpayer = dq._cap_tier_item(team, LAL_ID, roster, _ctx(cap_hits={1: 190_000_000}))
    assert taxpayer.priority == "medium"

    first_apron = dq._cap_tier_item(team, LAL_ID, roster, _ctx(cap_hits={1: 197_000_000}))
    assert first_apron.priority == "medium"

    second_apron = dq._cap_tier_item(team, LAL_ID, roster, _ctx(cap_hits={1: 210_000_000}))
    assert second_apron.priority == "high"
    assert "second apron" in second_apron.priority_reason


def test_cap_tier_item_always_appears_without_valuation():
    """Factual contract/cap item: survives even though it never touches the valuation model."""
    roster: list[Player] = []
    team = _team()

    item = dq._cap_tier_item(team, LAL_ID, roster, _ctx(cap_hits={}))

    assert item.type == dq.TYPE_CAP_TIER
    assert item.priority == "low"
    assert item.pay_usd == 0


def test_cap_tier_item_missing_cap_constants_has_caution():
    roster = [Player(player_id=1, current_team_id=LAL_ID)]
    team = _team()
    ctx = _ctx(caps={}, salary_cap=None, tax_line=None, first_apron=None, second_apron=None, cap_hits={1: 50_000_000})

    item = dq._cap_tier_item(team, LAL_ID, roster, ctx)

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
    assert item.destination == f"/free-agency?tab=targets&team={LAL_ID}"
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
        lambda player, team_id, ctx: (
            [_item(priority="high", type_=dq.TYPE_OPTION, player_id=player.player_id, id_=f"option:{player.player_id}")]
            if player.player_id == 1
            else [_item(priority="low", type_=dq.TYPE_EXTENSION, player_id=player.player_id, id_=f"extension:{player.player_id}")]
        ),
    )
    monkeypatch.setattr(
        dq, "_cap_tier_item",
        lambda team, team_id, roster, ctx: _item(priority="medium", type_=dq.TYPE_CAP_TIER, player_id=None, id_="cap_tier:team"),
    )
    monkeypatch.setattr(dq, "_roster_need_item", lambda db, team_id, roster, season: None)

    queue = dq.build_decision_queue(db, LAL_ID)

    assert queue.team_id == LAL_ID
    assert queue.team_name == "Los Angeles Lakers"
    assert queue.season == dq.LATEST_SEASON
    assert queue.generated_from == "latest"
    assert [i.id for i in queue.items] == ["option:1", "cap_tier:team", "extension:2"]
    assert queue.model_unavailable is False


def test_build_decision_queue_accepts_explicit_current_season(monkeypatch):
    team = _team()
    db = FakeDB(teams=[team], players=[])
    monkeypatch.setattr(dq, "load_season_caps", lambda db: dict(CAPS))
    monkeypatch.setattr(
        dq, "_cap_tier_item",
        lambda team, team_id, roster, ctx: _item(priority="low", type_=dq.TYPE_CAP_TIER, player_id=None, id_="cap_tier:team"),
    )
    monkeypatch.setattr(dq, "_roster_need_item", lambda db, team_id, roster, season: None)

    queue = dq.build_decision_queue(db, LAL_ID, dq.LATEST_SEASON)

    assert queue.season == dq.LATEST_SEASON
    assert queue.generated_from == "latest"


def test_build_decision_queue_rejects_non_current_season():
    """F1: the endpoint composes current contracts/rosters/valuations/roster-fit, so any
    season other than LATEST_SEASON is rejected rather than silently served."""
    team = _team()
    db = FakeDB(teams=[team], players=[])
    try:
        dq.build_decision_queue(db, LAL_ID, "2023-24")
        assert False, "expected ValueError"
    except ValueError as e:
        assert dq.LATEST_SEASON in str(e)


def test_build_decision_queue_degrades_extension_when_model_artifact_missing(monkeypatch):
    """B1: a globally missing model artifact must not drop extension items — eligible
    players still surface as low-priority contract facts with a caution, and the queue
    exposes model_unavailable so the frontend can explain the degraded run. Factual
    cap/contract items (cap_tier here) are unaffected."""
    team = _team()
    player = Player(player_id=1, full_name="Eligible Player", current_team_id=LAL_ID)
    contract = Contract(id=1, player_id=1, season_start="2023-24", years=1)
    contract_years = [
        ContractYear(contract_id=1, season="2026-27", cap_pct=0.15, is_player_option=False, is_team_option=False),
    ]
    db = FakeDB(teams=[team], players=[player], contracts=[contract], contract_years=contract_years)

    monkeypatch.setattr(dq, "load_season_caps", lambda db: dict(CAPS))
    monkeypatch.setattr(dq, "_current_option_pool_entering", lambda db: {})
    monkeypatch.setattr(dq, "_roster_need_item", lambda db, team_id, roster, season: None)
    monkeypatch.setattr(
        ext_module, "value_players",
        lambda db, targets: (_ for _ in ()).throw(FileNotFoundError("model artifact missing")),
    )

    queue = dq.build_decision_queue(db, LAL_ID)

    assert queue.model_unavailable is True
    assert "model artifact is unavailable" in queue.caveat

    extension_items = [i for i in queue.items if i.type == dq.TYPE_EXTENSION]
    assert len(extension_items) == 1
    assert extension_items[0].priority == "low"
    assert extension_items[0].caution is not None
    assert extension_items[0].player_id == 1

    cap_tier_items = [i for i in queue.items if i.type == dq.TYPE_CAP_TIER]
    assert len(cap_tier_items) == 1
    assert cap_tier_items[0].caution is None


# --------------------------------------------------------------------------- router
def test_router_unknown_team_404():
    db = FakeDB(teams=[])
    resp = _client(db).get("/decision-queue", params={"team_id": LAL_ID})
    assert resp.status_code == 404


def test_router_bad_season_422():
    db = FakeDB(teams=[_team()])
    resp = _client(db).get("/decision-queue", params={"team_id": LAL_ID, "season": "20xx"})
    assert resp.status_code == 422


def test_router_non_current_season_422():
    db = FakeDB(teams=[_team()])
    resp = _client(db).get("/decision-queue", params={"team_id": LAL_ID, "season": "2023-24"})
    assert resp.status_code == 422


def test_router_accepts_current_season(monkeypatch):
    canned = dq.DecisionQueue(
        team_id=LAL_ID, team_name="Los Angeles Lakers", season="2025-26", generated_from="latest",
        items=[], caveat="caveat text",
    )
    monkeypatch.setattr(dqr, "build_decision_queue", lambda db, team_id, season: canned)

    resp = _client(FakeDB()).get("/decision-queue", params={"team_id": LAL_ID, "season": dq.LATEST_SEASON})

    assert resp.status_code == 200


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
    assert body["model_unavailable"] is False
    assert not any(item["destination"].startswith("/trade") for item in body["items"])
