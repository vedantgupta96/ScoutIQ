"""Central config. Reads DATABASE_URL (and friends) from backend/.env."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"
RAW_DIR = DATA_DIR / "raw"  # cached BBRef HTML lives here


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    DATABASE_URL: str = ""

    # Seasons to ETL: 2012-13 .. 2024-25 (enough history for a 2015–22 / 2023–25 backtest).
    SEASON_START_YEAR: int = 2012
    SEASON_END_YEAR: int = 2024
    CURRENT_SEASON: str = "2025-26"

    # Politeness for Basketball-Reference scraping.
    BBREF_DELAY_SECONDS: float = 3.5
    BBREF_USER_AGENT: str = "ScoutIQ/0.1 (personal portfolio research; contact via github)"

    @property
    def seasons(self) -> list[str]:
        """['2012-13', '2013-14', ..., '2024-25'] — NBA season string format."""
        return [
            f"{y}-{str(y + 1)[-2:]}"
            for y in range(self.SEASON_START_YEAR, self.SEASON_END_YEAR + 1)
        ]

    @property
    def DATA_DIR(self):  # noqa: N802 — expose module path constants via settings
        return DATA_DIR

    @property
    def RAW_DIR(self):  # noqa: N802
        return RAW_DIR


settings = Settings()
