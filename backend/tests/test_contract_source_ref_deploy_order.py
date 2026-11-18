from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from scoutiq.api.deps import get_db
from scoutiq.api.main import app
from scoutiq.models import Base, Contract, ContractYear, Player, Team


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):
    return "JSON"


def _pre_0013_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for table in Base.metadata.sorted_tables:
        try:
            table.create(engine)
        except OperationalError:
            pass
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE contracts DROP COLUMN source_ref"))
        conn.execute(text("ALTER TABLE contracts DROP COLUMN remaining_guaranteed_usd"))
    return engine


def _seed(engine):
    with Session(engine) as s:
        s.add(Team(team_id=1, abbreviation="BOS", name="Boston Celtics"))
        s.add(Player(player_id=7, full_name="Test Player", current_team_id=1))
        s.flush()
        contract = Contract(player_id=7, team_id=1, season_start="2025-26", years=2, total_value=30, source="spotrac")
        contract.contract_years = [
            ContractYear(season="2025-26", aav=10, is_guaranteed=True),
            ContractYear(season="2026-27", aav=20, is_guaranteed=True),
        ]
        s.add(contract)
        s.commit()


def test_pre_migration_table_really_lacks_column():
    engine = _pre_0013_engine()
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(contracts)"))]
    assert "source_ref" not in cols and "remaining_guaranteed_usd" not in cols


def test_select_contract_and_years_work_without_source_ref_column():
    engine = _pre_0013_engine()
    _seed(engine)
    with Session(engine) as s:
        contract = s.scalars(select(Contract).where(Contract.player_id == 7)).one()
        assert (contract.season_start, contract.source, contract.total_value) == ("2025-26", "spotrac", 30)
        assert [(y.season, y.aav) for y in contract.contract_years] == [("2025-26", 10), ("2026-27", 20)]


def test_orm_insert_without_source_ref_works():
    engine = _pre_0013_engine()
    _seed(engine)
    with Session(engine) as s:
        s.add(Contract(player_id=7, season_start="2030-31", years=1, total_value=1, source="spotrac"))
        s.flush()
        assert s.scalar(select(Contract.id).where(Contract.season_start == "2030-31")) is not None


def test_contract_endpoint_returns_200_without_source_ref_column():
    engine = _pre_0013_engine()
    _seed(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    try:
        response = TestClient(app).get("/players/7/contract")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["remaining_guaranteed_usd"] is None
    assert body["guarantee_status"] == "known"


def test_contract_endpoint_reports_unknown_guarantees_and_total_when_column_exists():
    from scoutiq.api import schema_guard

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for table in Base.metadata.sorted_tables:
        try:
            table.create(engine)
        except OperationalError:
            pass
    with Session(engine) as s:
        s.add(Team(team_id=1, abbreviation="BOS", name="Boston Celtics"))
        s.add(Player(player_id=7, full_name="Test Player", current_team_id=1))
        s.flush()
        contract = Contract(player_id=7, team_id=1, season_start="2026-27", years=2, total_value=30,
                            source="sportsref_export", remaining_guaranteed_usd=10)
        contract.contract_years = [
            ContractYear(season="2026-27", aav=10, is_guaranteed=None),
            ContractYear(season="2027-28", aav=20, is_guaranteed=None, is_player_option=True),
        ]
        s.add(contract)
        s.commit()
    factory = sessionmaker(engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    schema_guard._present.clear()
    app.dependency_overrides[get_db] = override
    try:
        response = TestClient(app).get("/players/7/contract")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["remaining_guaranteed_usd"] == 10
    assert body["guarantee_status"] == "unknown"
    assert [y["is_guaranteed"] for y in body["years_detail"]] == [None, None]


def test_contract_caveat_is_source_aware_and_flags_unknown_guarantees():
    from scoutiq.api.routers.players import _contract_source_lead

    assert _contract_source_lead("spotrac") == "Spotrac forward contract structure."
    assert _contract_source_lead("sportsref_export") == "Sports Reference contract export (user-supplied snapshot)."
    assert _contract_source_lead("bbref_contracts") == "Basketball-Reference contract table."
    assert _contract_source_lead("other") == "other contract record."


def test_endpoint_caveat_for_sportsref_export_with_unknown_guarantees():
    from scoutiq.api import schema_guard

    engine = _pre_0013_engine()
    with Session(engine) as s:
        s.add(Team(team_id=1, abbreviation="BOS", name="Boston Celtics"))
        s.add(Player(player_id=7, full_name="Test Player", current_team_id=1))
        s.flush()
        contract = Contract(player_id=7, team_id=1, season_start="2026-27", years=1, total_value=10,
                            source="sportsref_export")
        contract.contract_years = [ContractYear(season="2026-27", aav=10, is_guaranteed=None)]
        s.add(contract)
        s.commit()
    factory = sessionmaker(engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    schema_guard._present.clear()
    app.dependency_overrides[get_db] = override
    try:
        caveat = TestClient(app).get("/players/7/contract").json()["caveat"]
    finally:
        app.dependency_overrides.clear()
    assert "Spotrac" not in caveat
    assert "Per-year guarantees are unknown where marked" in caveat
