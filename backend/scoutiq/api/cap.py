"""CBA cap thresholds — the one owner of tier ladders, apron proxies, cap projection, and
room-to-line arithmetic. cap_simulator builds on this; routers never touch a threshold literal.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from scoutiq.api.deps import DB
from scoutiq.api.season import next_season as _next_season
from scoutiq.api.season import validate_season
from scoutiq.models import CapConstants

CAP_GROWTH_RATE = 0.045  # 4.5% annual cap escalator for projection

# Payroll tiers, ordered from cheapest to most restrictive.
TIER_BELOW_TAX = "below-tax"
TIER_TAXPAYER = "taxpayer"
TIER_FIRST_APRON = "first-apron"
TIER_SECOND_APRON = "second-apron"
TIER_ORDER = [TIER_BELOW_TAX, TIER_TAXPAYER, TIER_FIRST_APRON, TIER_SECOND_APRON]

# The roster-building tools each tier costs you under the 2023 CBA. Phrased as the
# consequences of *being in* that tier, most-cited restrictions first.
APRON_CONSEQUENCES: dict[str, list[str]] = {
    TIER_BELOW_TAX: [],
    TIER_TAXPAYER: [
        "Owes luxury tax on every dollar above the tax line (escalating brackets).",
        "Repeater-tax rates apply if taxed in 3 of the prior 4 seasons.",
    ],
    TIER_FIRST_APRON: [
        "Hard-capped at the first apron once any apron tool is used.",
        "Limited to the taxpayer mid-level exception; loses the full non-taxpayer MLE.",
        "Cannot acquire a player via sign-and-trade.",
        "Cannot use the bi-annual exception or send cash out in trades.",
    ],
    TIER_SECOND_APRON: [
        "Hard-capped at the second apron.",
        "Cannot aggregate two-plus salaries to match in a trade.",
        "No mid-level exception of any kind.",
        "Cannot take back more salary than is sent out in a trade.",
        "Future first-round pick frozen, then moved to end of the round if it persists.",
    ],
}


def classify_tier(
    payroll: int, tax: int | None, first_apron: int | None, second_apron: int | None
) -> str:
    """Bucket a payroll into its cap tier; thresholds may be None (unknown)."""
    if second_apron and payroll >= second_apron:
        return TIER_SECOND_APRON
    if first_apron and payroll >= first_apron:
        return TIER_FIRST_APRON
    if tax and payroll >= tax:
        return TIER_TAXPAYER
    return TIER_BELOW_TAX


@dataclass
class SeasonCapData:
    season: str
    salary_cap: int
    tax_line: int
    first_apron: int
    second_apron: int
    is_projected: bool = False


def _project_cap(base_cap: SeasonCapData, years_forward: int) -> SeasonCapData:
    """Project cap thresholds forward from a base season using CAP_GROWTH_RATE."""
    factor = (1 + CAP_GROWTH_RATE) ** years_forward
    # tax/apron margins are typically set by CBA ratio; we scale them proportionally
    return SeasonCapData(
        season=base_cap.season,  # caller overwrites
        salary_cap=int(base_cap.salary_cap * factor),
        tax_line=int(base_cap.tax_line * factor),
        first_apron=int(base_cap.first_apron * factor),
        second_apron=int(base_cap.second_apron * factor),
        is_projected=True,
    )


def build_season_sequence(
    start_season: str,
    years: int,
    cap_by_season: dict[str, SeasonCapData],
) -> list[SeasonCapData]:
    """Return cap data for `years` seasons starting at start_season.

    Uses DB data when available; projects forward otherwise.
    Season format: 'YYYY-YY' (e.g. '2025-26').
    """
    validate_season(start_season)

    # find last known base for projection
    all_known = sorted(cap_by_season.keys())
    last_known = cap_by_season[all_known[-1]] if all_known else None

    result = []
    current = start_season
    for _ in range(years):
        if current in cap_by_season:
            raw = cap_by_season[current]
            data = SeasonCapData(
                season=current,
                salary_cap=raw.salary_cap,
                tax_line=raw.tax_line,
                first_apron=raw.first_apron,
                second_apron=raw.second_apron,
                is_projected=False,
            )
        elif last_known is not None:
            # project forward
            base_year = int(all_known[-1][:4])
            target_year = int(current[:4])
            offset = target_year - base_year
            data = _project_cap(last_known, offset)
        else:
            raise ValueError("No cap constants available to project from.")
        data = SeasonCapData(
            current,
            data.salary_cap,
            data.tax_line,
            data.first_apron,
            data.second_apron,
            data.is_projected,
        )
        result.append(data)
        current = _next_season(current)
    return result


# Apron thresholds for seasons before the 2023-24 CBA defined them, scaled from the tax line.
APRON_FIRST_PROXY = 1.032
APRON_SECOND_PROXY = 1.097


def apron_values(cap_row: CapConstants | None) -> tuple[int | None, int | None]:
    """First/second apron, falling back to a tax-line proxy before the 2023-24 CBA."""
    if cap_row is None:
        return None, None
    first = cap_row.first_apron or (
        int(cap_row.tax_line * APRON_FIRST_PROXY) if cap_row.tax_line else None
    )
    second = cap_row.second_apron or (
        int(cap_row.tax_line * APRON_SECOND_PROXY) if cap_row.tax_line else None
    )
    return first, second


def season_cap_from_row(row: CapConstants) -> SeasonCapData | None:
    """One DB row as SeasonCapData, or None if it lacks a cap or tax line to build from."""
    if not row.salary_cap or not row.tax_line:
        return None
    first_apron, second_apron = apron_values(row)
    return SeasonCapData(
        season=row.season,
        salary_cap=row.salary_cap,
        tax_line=row.tax_line,
        first_apron=first_apron,
        second_apron=second_apron,
    )


def load_season_caps(db: DB) -> dict[str, SeasonCapData]:
    """All DB cap constants as SeasonCapData, apron gaps filled by the tax-line proxy."""
    caps: dict[str, SeasonCapData] = {}
    for row in db.scalars(select(CapConstants)).all():
        data = season_cap_from_row(row)
        if data is not None:
            caps[row.season] = data
    return caps


def cap_for(season: str, caps: dict[str, SeasonCapData]) -> SeasonCapData | None:
    """Cap data for `season`, projecting forward at the CBA escalator when it isn't stored."""
    if not caps:
        return None
    try:
        return build_season_sequence(season, 1, caps)[0]
    except (ValueError, KeyError):
        return caps.get(season)


@dataclass
class RoomToLines:
    room_to_cap: int | None
    room_to_tax: int | None
    room_to_first_apron: int | None
    room_to_second_apron: int | None


def room_to_lines(
    payroll: int,
    *,
    salary_cap: int | None,
    tax_line: int | None,
    first_apron: int | None,
    second_apron: int | None,
) -> RoomToLines:
    """Signed room from payroll to each cap line; negative means already over it."""
    return RoomToLines(
        room_to_cap=(salary_cap - payroll) if salary_cap else None,
        room_to_tax=(tax_line - payroll) if tax_line else None,
        room_to_first_apron=(first_apron - payroll) if first_apron else None,
        room_to_second_apron=(second_apron - payroll) if second_apron else None,
    )
