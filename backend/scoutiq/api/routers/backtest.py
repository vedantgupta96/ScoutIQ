"""GET /backtest — committed valuation-model backtest metadata and valuation rows."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "model" / "artifacts"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"
VALUATIONS_PATH = ARTIFACT_DIR / "valuations_test.csv"

router = APIRouter(tags=["model"])


class ValuationRow(BaseModel):
    full_name: str
    next_season: str
    actual_pct: float
    value_pct: float
    gap_pct: float


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


@router.get("/backtest/valuations", response_model=list[ValuationRow])
def get_backtest_valuations():
    """Return all rows from the committed test-set valuation artifact."""
    if not VALUATIONS_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="valuations_test.csv artifact is missing. Run `python -m scoutiq.model.train`.",
        )
    rows: list[ValuationRow] = []
    with VALUATIONS_PATH.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(ValuationRow(
                full_name=row["full_name"],
                next_season=row["next_season"],
                actual_pct=float(row["actual_pct"]),
                value_pct=float(row["value_pct"]),
                gap_pct=float(row["gap_pct"]),
            ))
    return rows
