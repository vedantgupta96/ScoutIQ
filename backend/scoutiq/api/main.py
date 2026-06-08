"""ScoutIQ FastAPI application.

Start with:  uvicorn scoutiq.api.main:app --reload --app-dir /path/to/backend
Or from backend/: uvicorn scoutiq.api.main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scoutiq.api.routers import backtest, headshots, health, llm_eval, players, simulator, teams

app = FastAPI(
    title="ScoutIQ API",
    description="Explainable NBA Contract Intelligence — valuation model + cap simulator.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(headshots.router)
app.include_router(players.router)
app.include_router(teams.router)
app.include_router(simulator.router)
app.include_router(backtest.router)
app.include_router(llm_eval.router)
