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

    # Seasons to ETL: 2012-13 .. 2025-26 (enough history for a 2015–22 / 2023–25 backtest).
    SEASON_START_YEAR: int = 2012
    SEASON_END_YEAR: int = 2025
    CURRENT_SEASON: str = "2025-26"

    # Politeness for Basketball-Reference scraping.
    BBREF_DELAY_SECONDS: float = 3.5
    BBREF_USER_AGENT: str = "ScoutIQ/0.1 (personal portfolio research; contact via github)"

    # Qualitative scouting backfills. Sonar is for WORDS only, never stats/salary/cap.
    # Most API scouting endpoints serve cached DB rows; the rationale endpoint below is the live exception.
    PERPLEXITY_API_KEY: str = ""
    SONAR_MODEL: str = "sonar"
    ANTHROPIC_API_KEY: str = ""
    SCOUTIQ_LLM_MODEL: str = "claude-sonnet-4-6"

    # Grounded rationale generation. UNLIKE the scouting/eval layers, the rationale endpoint may call
    # Claude (and, in multi_source mode, Sonar) LIVE — a deliberate, scoped exception. Results are cached
    # in player_rationales; ?refresh=true forces a fresh generation.
    RATIONALE_CONSENSUS_MODE: str = "fusion"   # "fusion" | "multi_source"
    RATIONALE_MULTI_SOURCE_N: int = 3          # # of Sonar angles fetched in multi_source mode

    @property
    def seasons(self) -> list[str]:
        """['2012-13', '2013-14', ..., '2025-26'] — NBA season string format."""
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
