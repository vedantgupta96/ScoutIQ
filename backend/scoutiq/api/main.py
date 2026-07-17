"""ScoutIQ FastAPI application.

Start with:  uvicorn scoutiq.api.main:app --reload --app-dir /path/to/backend
Or from backend/: uvicorn scoutiq.api.main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scoutiq.api.routers import (
    backtest,
    free_agency,
    headshots,
    health,
    llm_eval,
    offseason,
    players,
    simulator,
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

app.include_router(health.router)
app.include_router(headshots.router)
app.include_router(players.router)
app.include_router(teams.router)
app.include_router(free_agency.router)
app.include_router(offseason.router)
app.include_router(trades.router)
app.include_router(simulator.router)
app.include_router(backtest.router)
app.include_router(llm_eval.router)
