"""Pure parser for the Sports Reference (Basketball-Reference) player contracts table export.

The export is an HTML document saved with an .xls extension. It is untrusted data: this module only
reads it and never executes anything from it. No DB, no network, no totals, no collapsing by player."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import html as lxml_html

from scoutiq.api.season import is_valid_season

MARKER_SEMANTICS = {"salary-pl": "player_option", "salary-tm": "team_option"}

LEGEND_EVIDENCE = (
    "The Color Key on https://www.basketball-reference.com/contracts/players.html (cached copy dated "
    "2026-07-09 at backend/scoutiq/data/raw/bbref_contracts_players.html) defines salary-pl as Player "
    "Option and salary-tm as Team Option, and remain_gtd as 'The amount of a player's remaining salary "
    "that is guaranteed.' No other salary-* classes appear there. The export itself carries no legend."
)

_YEAR_STAT = re.compile(r"^y(\d+)$")


class ExportFormatError(ValueError):
    pass


@dataclass
class YearCell:
    season: str
    amount: int | None
    option: str | None
    blank: bool


@dataclass
class ObligationRow:
    row_ordinal: int
    source_rank: int | None
    bbref_id: str
    player_name: str
    team_abbr: str
    years: list[YearCell]
    remaining_guaranteed: int | None


@dataclass
class ParsedExport:
    seasons: list[str]
    rows: list[ObligationRow]
    problems: list[str]
    skipped_rows: int = 0
    option_class_counts: dict[str, int] = field(default_factory=dict)


def _text(el) -> str:
    return " ".join(el.text_content().split())


def _classes(el) -> list[str]:
    return (el.get("class") or "").split()


def _parse_header(doc) -> tuple[list[tuple[str, int]], list[str]]:
    header_cells = None
    for tr in doc.iter("tr"):
        ths = tr.findall("th")
        if any(th.get("data-stat") == "player" for th in ths):
            header_cells = ths
            break
    if header_cells is None:
        raise ExportFormatError("header row with a player column not found")
    stats = {th.get("data-stat"): th for th in header_cells if th.get("data-stat")}
    for required in ("player", "team_id", "remain_gtd"):
        if required not in stats:
            raise ExportFormatError(f"header is missing required column {required!r}")
    year_cols: list[tuple[int, str, str]] = []
    for stat, th in stats.items():
        m = _YEAR_STAT.match(stat)
        if m:
            label = _text(th) or (th.get("aria-label") or "").strip()
            year_cols.append((int(m.group(1)), stat, label))
    if not year_cols:
        raise ExportFormatError("header has no y1..yN season columns")
    year_cols.sort()
    seasons: list[str] = []
    for _, stat, label in year_cols:
        if not is_valid_season(label):
            raise ExportFormatError(f"column {stat} label {label!r} is not a valid YYYY-YY season")
        seasons.append(label)
    for earlier, later in zip(seasons, seasons[1:]):
        if int(later[:4]) != int(earlier[:4]) + 1:
            raise ExportFormatError(f"seasons are not consecutive: {earlier} then {later}")
    ordinals = [n for n, _, _ in year_cols]
    if ordinals != list(range(1, len(ordinals) + 1)):
        raise ExportFormatError("year columns are not a contiguous y1..yN run")
    return [(stat, i) for i, (_, stat, _) in enumerate(year_cols)], seasons


def _digits_amount(text: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def _read_amount(cell, where: str, problems: list[str]) -> tuple[int | None, bool]:
    text = _text(cell)
    csk = (cell.get("csk") or "").strip()
    shown = _digits_amount(text)
    if csk:
        try:
            value = int(csk)
        except ValueError:
            problems.append(f"{where}: csk {csk!r} is not an integer")
            return shown, shown is None
        if shown is not None and shown != value:
            problems.append(f"{where}: csk {value} disagrees with displayed text {text!r}")
        return value, False
    if shown is None:
        return None, True
    return shown, False


def parse_export(html: str) -> ParsedExport:
    html = re.sub(r"^\s*<\?xml[^>]*\?>", "", html)
    try:
        doc = lxml_html.fromstring(html)
    except Exception as exc:
        raise ExportFormatError(f"document is not parseable HTML: {exc}") from exc
    year_stats, seasons = _parse_header(doc)
    problems: list[str] = []
    rows: list[ObligationRow] = []
    option_class_counts: dict[str, int] = {}
    skipped = 0
    ordinal = 0
    for tbody in doc.iter("tbody"):
        for tr in tbody.findall("tr"):
            if "thead" in _classes(tr):
                continue
            cells = {c.get("data-stat"): c for c in tr if c.tag in ("td", "th") and c.get("data-stat")}
            if "player" not in cells:
                continue
            this_ordinal = ordinal
            ordinal += 1
            player_cell = cells["player"]
            bbref_id = (player_cell.get("data-append-csv") or "").strip()
            name = _text(player_cell)
            if not bbref_id:
                problems.append(f"row {this_ordinal} ({name!r}): missing data-append-csv; row skipped")
                skipped += 1
                continue
            where_row = f"row {this_ordinal} ({bbref_id})"
            rank_cell = cells.get("ranker")
            rank = None
            if rank_cell is not None:
                rank = _digits_amount(rank_cell.get("csk") or _text(rank_cell))
            team_cell = cells.get("team_id")
            team = _text(team_cell) if team_cell is not None else ""
            if not team:
                problems.append(f"{where_row}: missing or empty team_id cell")
            years: list[YearCell] = []
            for stat, idx in year_stats:
                cell = cells.get(stat)
                where = f"{where_row} {seasons[idx]}"
                if cell is None:
                    years.append(YearCell(seasons[idx], None, None, True))
                    continue
                amount, blank = _read_amount(cell, where, problems)
                option = None
                for cls in _classes(cell):
                    if cls.startswith("salary-"):
                        if cls in MARKER_SEMANTICS:
                            option = MARKER_SEMANTICS[cls]
                            option_class_counts[cls] = option_class_counts.get(cls, 0) + 1
                        else:
                            problems.append(f"{where}: unknown cell class {cls!r}")
                years.append(YearCell(seasons[idx], amount, option, blank))
            gtd_cell = cells.get("remain_gtd")
            gtd = None
            if gtd_cell is not None:
                gtd, _ = _read_amount(gtd_cell, f"{where_row} remain_gtd", problems)
            rows.append(ObligationRow(this_ordinal, rank, bbref_id, name, team, years, gtd))
    return ParsedExport(seasons, rows, problems, skipped, option_class_counts)
