"""Cap simulator logic — simplified 2023 CBA subset.

Rules modeled:
  - Salary cap / luxury tax line
  - First apron (~$5M above tax) — triggers sign-and-trade restrictions, trade aggregation limits
  - Second apron (~$16M above tax) — hard cap, most restrictive tier

Not modeled: Bird rights, MLE/BAE size reductions, repeater tax, traded-player exceptions.
The frontend shows a disclaimer noting this is a simplified model.

Cap projection for future seasons: if a season isn't in the DB, we project the cap forward
at CAP_GROWTH_RATE per year from the last known value. The NBA CBA typically escalates the cap
~4–5% annually; 4.5% is a reasonable center estimate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from scoutiq.api.season import next_season as _next_season
from scoutiq.api.season import validate_season

CAP_GROWTH_RATE = 0.045  # 4.5% annual cap escalator for projection
SIMULATOR_ASSUMPTIONS = {
    "standalone_contract_only": True,
    "simplified_cba": True,
    "cap_projection_rate": CAP_GROWTH_RATE,
    "not_modeled": [
        "team payroll",
        "luxury tax owed",
        "Bird rights",
        "MLE/BAE exceptions",
        "repeater tax",
        "traded-player exceptions",
    ],
}


@dataclass
class SeasonCapData:
    season: str
    salary_cap: int
    tax_line: int
    first_apron: int
    second_apron: int
    is_projected: bool = False


@dataclass
class ContractYear:
    season: str
    cap_hit_usd: int
    cap_hit_pct: float          # e.g. 20.0 means 20%
    is_guaranteed: bool
    is_player_option: bool
    is_team_option: bool
    salary_cap: int
    tax_line: int
    first_apron: int
    second_apron: int
    is_projected_cap: bool


@dataclass
class CapSimulation:
    player_id: int
    player_name: str
    proposed_aav_pct: float     # as %, e.g. 20.0
    proposed_aav_usd: int       # dollars (first year)
    value_pct: float | None     # model's production-implied value (% of cap)
    value_usd: int | None
    lo_pct: float | None
    hi_pct: float | None
    value_gap_pct: float | None # value_pct - proposed_aav_pct (positive = underpaid)
    model_version: str | None
    assumptions: dict = field(default_factory=lambda: dict(SIMULATOR_ASSUMPTIONS))
    years: list[ContractYear] = field(default_factory=list)


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


def simulate(
    player_id: int,
    player_name: str,
    aav_pct: float,            # % of cap (e.g. 20.0)
    years: int,
    guaranteed_years: int | None,
    player_option_years: int,
    team_option_years: int,
    start_season: str,
    cap_by_season: dict[str, SeasonCapData],
    valuation: dict | None = None,  # output of predict_from_features / predict_for_player
) -> CapSimulation:
    """Run the cap simulation.

    Option logic (applied from the END of the contract):
    - team_option_years: last N years are team options
    - player_option_years: preceding M years are player options
    - guaranteed_years: all remaining years up to that count are guaranteed; if omitted, all
      non-option years are treated as guaranteed.
    """
    if years < 1:
        raise ValueError("years must be at least 1.")
    if any(v < 0 for v in (player_option_years, team_option_years)):
        raise ValueError("option year counts cannot be negative.")
    option_years = player_option_years + team_option_years
    if option_years > years:
        raise ValueError("player_option_years + team_option_years cannot exceed years.")
    if guaranteed_years is None:
        guaranteed_years = years - option_years
    if guaranteed_years < 0:
        raise ValueError("guaranteed_years cannot be negative.")
    if guaranteed_years + option_years > years:
        raise ValueError(
            "guaranteed_years + player_option_years + team_option_years cannot exceed years."
        )

    aav_fraction = aav_pct / 100.0
    season_caps = build_season_sequence(start_season, years, cap_by_season)

    # Classify each year's guarantee/option status.
    # Convention: guaranteed years fill from start; options apply at the end.
    # E.g. 4yr deal, 3 guaranteed, 1 team option → [G, G, G, TO]
    year_types: list[tuple[bool, bool, bool]] = []  # (guaranteed, player_opt, team_opt)
    total = years
    remaining = total
    team_opts = min(team_option_years, remaining)
    remaining -= team_opts
    player_opts = min(player_option_years, remaining)
    remaining -= player_opts
    guaranteed = min(guaranteed_years, remaining)

    for i in range(total):
        is_g = i < guaranteed
        is_po = (guaranteed <= i < guaranteed + player_opts)
        is_to = (i >= total - team_opts)
        year_types.append((is_g, is_po, is_to))

    contract_years_out = []
    for i, (cap_data, (is_g, is_po, is_to)) in enumerate(zip(season_caps, year_types)):
        cap_hit_usd = int(aav_fraction * cap_data.salary_cap)
        cap_hit_pct = round(aav_fraction * 100, 2)
        contract_years_out.append(ContractYear(
            season=cap_data.season,
            cap_hit_usd=cap_hit_usd,
            cap_hit_pct=cap_hit_pct,
            is_guaranteed=is_g,
            is_player_option=is_po,
            is_team_option=is_to,
            salary_cap=cap_data.salary_cap,
            tax_line=cap_data.tax_line,
            first_apron=cap_data.first_apron,
            second_apron=cap_data.second_apron,
            is_projected_cap=cap_data.is_projected,
        ))

    # first-year USD for the summary
    first_year_usd = contract_years_out[0].cap_hit_usd if contract_years_out else 0
    value_pct = valuation["value_pct"] if valuation else None
    value_usd = int(value_pct / 100 * season_caps[0].salary_cap) if value_pct is not None else None
    gap = round(value_pct - aav_pct, 2) if value_pct is not None else None

    return CapSimulation(
        player_id=player_id,
        player_name=player_name,
        proposed_aav_pct=aav_pct,
        proposed_aav_usd=first_year_usd,
        value_pct=value_pct,
        value_usd=value_usd,
        lo_pct=valuation.get("lo_pct") if valuation else None,
        hi_pct=valuation.get("hi_pct") if valuation else None,
        value_gap_pct=gap,
        model_version=valuation.get("model_version") if valuation else None,
        years=contract_years_out,
    )
