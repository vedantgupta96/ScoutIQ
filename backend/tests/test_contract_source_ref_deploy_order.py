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
    assert "source_ref" not in cols


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
    assert response.json()
