"""ScoutIQ FastAPI application.

Start with:  uvicorn scoutiq.api.main:app --reload --app-dir /path/to/backend
Or from backend/: uvicorn scoutiq.api.main:app --reload
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from scoutiq.api.routers import (
    backtest,
    free_agency,
    headshots,
    health,
    league,
    llm_eval,
    offseason,
    players,
    simulator,
    strategy,
    teams,
    trades,
)
from scoutiq.config import settings

app = FastAPI(
    title="ScoutIQ API",
    description="Explainable NBA Contract Intelligence — valuation model + cap simulator.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    # Local Next.js dev by default; production sets CORS_ORIGINS to the
    # deployed frontend origin(s), comma-separated.
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Valuation-backed reads change only when ETL/publish runs (≈ daily at most), so let
# browsers and CDNs reuse them: 5 min fresh, then serve stale while revalidating.
# Endpoints that set their own Cache-Control (headshots, logos, trade workspace) win.
_DEFAULT_CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=3600"


@app.middleware("http")
async def default_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if (
        request.method == "GET"
        and response.status_code == 200
        and "cache-control" not in response.headers
    ):
        response.headers["Cache-Control"] = _DEFAULT_CACHE_CONTROL
    return response


app.include_router(health.router)
app.include_router(headshots.router)
app.include_router(players.router)
app.include_router(teams.router)
app.include_router(league.router)
app.include_router(free_agency.router)
app.include_router(offseason.router)
app.include_router(trades.router)
app.include_router(simulator.router)
app.include_router(backtest.router)
app.include_router(strategy.router)
app.include_router(llm_eval.router)
