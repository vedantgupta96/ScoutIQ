"""GET /backtest — committed valuation-model backtest metadata."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "model" / "artifacts"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"

router = APIRouter(tags=["model"])


class BacktestResponse(BaseModel):
    model_version: str | None
    metrics: dict[str, Any]
    report_path: str
    artifacts: list[str]
    caveat: str


@router.get("/backtest", response_model=BacktestResponse)
def get_backtest():
    """Return metadata for the published v0 valuation backtest."""
    if not METRICS_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Backtest metrics artifact is missing. Run `python -m scoutiq.model.train`.",
        )

    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    artifacts = sorted(p.name for p in ARTIFACT_DIR.iterdir() if p.is_file() and p.name != "model.joblib")

    return BacktestResponse(
        model_version=metrics.get("model_version"),
        metrics=metrics,
        report_path="scoutiq/model/artifacts/report.md",
        artifacts=artifacts,
        caveat=(
            "The v0 model estimates production-implied value and intentionally excludes current salary. "
            "Contract-decision-point valuation is deferred until forward contract data is audited."
        ),
    )
