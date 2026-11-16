"""Offline parsers for historical contract-decision data (spike, SCO-20).

Pure functions over cached Basketball-Reference player pages (transaction log and
per-team salary table) and Spotrac player pages (contract blocks). No network, no DB.
Transaction text is preserved after tag-stripping; classification is rule-based and
conservative (`other` when nothing matches).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

SIGNING_KINDS = (
    "standard",
    "extension",
    "conversion",
    "rest_of_season",
    "two_way",
    "ten_day",
    "exhibit",
    "substitution",
)

LEAGUE_YEAR_ROLLOVER = {2020: date(2020, 10, 12), 2021: date(2021, 7, 21)}

SEASON_OPENERS = {
    "2012-13": date(2012, 10, 30),
    "2013-14": date(2013, 10, 29),
    "2014-15": date(2014, 10, 28),
    "2015-16": date(2015, 10, 27),
    "2016-17": date(2016, 10, 25),
    "2017-18": date(2017, 10, 17),
    "2018-19": date(2018, 10, 16),
    "2019-20": date(2019, 10, 22),
    "2020-21": date(2020, 12, 22),
    "2021-22": date(2021, 10, 19),
    "2022-23": date(2022, 10, 18),
    "2023-24": date(2023, 10, 24),
    "2024-25": date(2024, 10, 22),
    "2025-26": date(2025, 10, 21),
}

_FIRST_NAME_ALIASES = {
    "bones": "nahshon",
    "cam": "cameron",
    "herb": "herbert",
    "nic": "nicolas",
    "ron": "ronald",
    "svi": "sviatoslav",
}


@dataclass(frozen=True)
class Transaction:
    date: date | None
    text: str
    kind: str
    team: str | None


@dataclass(frozen=True)
class DraftInfo:
    year: int
    round: int
    pick: int | None


@dataclass(frozen=True)
class SalaryRow:
    season: str
    team: str
    salary: int


@dataclass(frozen=True)
class SpotracContract:
    start_year: int
    end_year: int
    first_season: str
    type_label: str
    is_current: bool
    is_upcoming: bool
    years: int | None
    total_value: int | None
    aav: int | None
    gtd_at_sign: int | None
    total_gtd: int | None
    signed_using: str | None
    fa_year: int | None
    fa_status: str | None


def league_year(d: date) -> int:
    rollover = LEAGUE_YEAR_ROLLOVER.get(d.year, date(d.year, 7, 1))
    return d.year if d >= rollover else d.year - 1


def season_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def signing_phase(d: date) -> str:
    season = season_label(league_year(d))
    opener = SEASON_OPENERS.get(season)
    if opener is not None:
        return "offseason" if d < opener else "in_season"
    return "offseason" if d.month in (7, 8, 9) else "in_season"


def normalize_person_name(name: str) -> str:
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower()
    n = re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv)$", "", n)
    n = re.sub(r"[^a-z\s]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    parts = n.split()
    if parts and parts[0] in _FIRST_NAME_ALIASES:
        parts[0] = _FIRST_NAME_ALIASES[parts[0]]
    return " ".join(parts)


def classify_transaction(text: str) -> str:
    t = text.lower().strip()
    if t.startswith("drafted by"):
        return "draft"
    if t.startswith(("signed", "re-signed", "converted from a two-way")):
        if "contract extension" in t:
            return "extension"
        if t.startswith("converted from a two-way"):
            return "conversion"
        if "two-way contract" in t:
            return "two_way"
        if "exhibit" in t:
            return "exhibit"
        if "substitution contract" in t:
            return "substitution"
        if "rest of the season" in t:
            return "rest_of_season"
        if re.search(r"\d+-day contract", t):
            return "ten_day"
        return "standard"
    if t.startswith("waived by"):
        return "waived"
    if t.startswith("released"):
        return "released"
    if t.startswith(("traded by", "as part of a")):
        return "traded"
    if t.startswith("claimed on waivers"):
        return "claimed"
    return "other"


_COMBINED_FORM_RE = re.compile(
    r"then signed|\d+-day contract|two-way contract|exhibit|substitution contract"
)


def entry_combines_forms(text: str, kind: str) -> bool:
    if kind not in ("standard", "rest_of_season"):
        return False
    return _COMBINED_FORM_RE.search(text.lower()) is not None


_TEAM_STOP = r"(?:\.|;|,| from the | in the | to the | \()"
_DEST_STOP = r"(?:\.|;|,| for | in | \()"


def _extract_team(text: str, kind: str) -> str | None:
    if kind == "traded":
        m = re.search(r" to the (.*?)(?:" + _DEST_STOP + r"|$)", text)
    elif kind in SIGNING_KINDS or kind in ("draft", "claimed", "waived"):
        m = re.search(r"(?:with the |by the )(.*?)(?:" + _TEAM_STOP + r"|$)", text)
    else:
        return None
    if not m:
        return None
    team = m.group(1).strip()
    return team or None


_DRAFT_RE = re.compile(
    r"drafted by the .*? in the (\d+)(?:st|nd|rd|th) round"
    r"(?: \((\d+)(?:st|nd|rd|th) pick\))? of the (\d{4}) nba draft",
    re.I,
)


def parse_draft(text: str) -> DraftInfo | None:
    m = _DRAFT_RE.search(text)
    if not m:
        return None
    return DraftInfo(
        year=int(m.group(3)),
        round=int(m.group(1)),
        pick=int(m.group(2)) if m.group(2) else None,
    )


_TXN_RE = re.compile(r'<p class="transaction\s*">\s*<strong>([^<]+)</strong>:\s*(.*?)</p>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", fragment)).strip()


def _parse_date(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip(), "%B %d, %Y").date()
    except ValueError:
        return None


def parse_bbref_transactions(html: str) -> list[Transaction]:
    out: list[Transaction] = []
    for m in _TXN_RE.finditer(html):
        text = _clean(m.group(2))
        kind = classify_transaction(text)
        out.append(
            Transaction(
                date=_parse_date(m.group(1)),
                text=text,
                kind=kind,
                team=_extract_team(text, kind),
            )
        )
    return out


_SALARY_TABLE_RE = re.compile(r'<table[^>]*id="all_salaries".*?</table>', re.S)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S)
_SEASON_CELL_RE = re.compile(r'<th[^>]*data-stat="season"[^>]*>(.*?)</th>', re.S)
_TEAM_CELL_RE = re.compile(r'<td[^>]*data-stat="team_name"[^>]*>(.*?)</td>', re.S)
_SALARY_CELL_RE = re.compile(r'<td[^>]*data-stat="salary"[^>]*>(.*?)</td>', re.S)
_SEASON_RE = re.compile(r"^\d{4}-\d{2}$")


def parse_bbref_salary_rows(html: str) -> list[SalaryRow]:
    table = _SALARY_TABLE_RE.search(html)
    if not table:
        return []
    out: list[SalaryRow] = []
    for row in _ROW_RE.finditer(table.group(0)):
        body = row.group(1)
        s, t, sal = _SEASON_CELL_RE.search(body), _TEAM_CELL_RE.search(body), _SALARY_CELL_RE.search(body)
        if not (s and t and sal):
            continue
        season = _clean(s.group(1))
        digits = re.sub(r"\D", "", _clean(sal.group(1)))
        if not _SEASON_RE.match(season) or not digits:
            continue
        out.append(SalaryRow(season=season, team=_clean(t.group(1)), salary=int(digits)))
    return out


def parse_spotrac_player_name(html: str) -> str | None:
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if h1 and _clean(h1.group(1)):
        return _clean(h1.group(1))
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    if not m:
        return None
    name = re.sub(r"\s+Contract, Salary.*$", "", m.group(1).split("|")[0].strip())
    return name or None


_SIGNED_USING_MAP = {
    "minimum": "minimum",
    "bird rights": "bird",
    "early bird rights": "early-bird",
    "non-bird rights": "non-bird",
    "non-taxpayer mle": "non-taxpayer-mle",
    "non-taxpayer-mid-level-exception": "non-taxpayer-mle",
    "taxpayer mle": "taxpayer-mle",
    "room-mid-level-exception": "room-mle",
    "bi-annual": "bi-annual",
    "bi-annual-exception": "bi-annual",
    "rookie-scale-exception": "rookie-scale",
    "second-round-exception": "second-round",
    "cap-space": "cap-space",
    "qualifying-offer": "qualifying-offer",
    "sign-and-trade": "sign-and-trade",
}


def normalize_signed_using(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = raw.strip().lower()
    if not key:
        return None
    return _SIGNED_USING_MAP.get(key, key)


def spotrac_form_class(type_label: str) -> str:
    if "extension" in type_label or "extend-and-trade" in type_label:
        return "extension"
    if "two-way" in type_label:
        return "two_way"
    if "exhibit" in type_label or "ten-day" in type_label or "camp invite" in type_label:
        return "short_form"
    return "standard_form"


def event_form_class(kind: str) -> str:
    if kind in ("standard", "rest_of_season", "conversion"):
        return "standard_form"
    if kind == "two_way":
        return "two_way"
    if kind in ("ten_day", "exhibit", "substitution"):
        return "short_form"
    return "extension"


_WRAPPER_SPLIT = '<div class="contract-wrapper'
_HEADING_RE = re.compile(r'<span class="years">(.*?)</span>\s*</h2>', re.S)
_YEARS_RE = re.compile(r"(\d{4})-(\d{4})")
_STATUS_RE = re.compile(r"\((current|pending|upcoming extension)\)", re.I)
_CELL_RE = re.compile(r'<div class="label">([^<]*)</div>\s*<div class="value">(.*?)</div>', re.S)


def _money(raw: str | None) -> int | None:
    if not raw:
        return None
    m = re.search(r"\$\s*([\d,]+)", raw)
    if not m:
        return None
    digits = m.group(1).replace(",", "")
    return int(digits) if digits else None


def parse_spotrac_contracts(html: str) -> list[SpotracContract]:
    out: list[SpotracContract] = []
    for block in html.split(_WRAPPER_SPLIT)[1:]:
        head = _HEADING_RE.search(block)
        if not head:
            continue
        heading = _clean(head.group(1))
        ym = _YEARS_RE.search(heading)
        if not ym:
            continue
        statuses = [s.lower() for s in _STATUS_RE.findall(heading)]
        label = _STATUS_RE.sub("", heading[ym.end():])
        type_label = re.sub(r"\s+", " ", label).strip().lower()
        cut = block.find("contract-toggle")
        details = block if cut < 0 else block[:cut]
        cells: dict[str, str] = {}
        for lab, val in _CELL_RE.findall(details):
            cells.setdefault(lab.strip().rstrip(":").lower(), _clean(val))
        terms = cells.get("contract terms", "")
        yrs = re.search(r"(\d+) yr\(s\)", terms)
        fa_year = fa_status = None
        fa = re.search(r"(\d{4})(?:\s*/\s*([A-Za-z]+))?", cells.get("free agent", ""))
        if fa:
            fa_year = int(fa.group(1))
            if fa.group(2) and fa.group(2).lower() in ("ufa", "rfa"):
                fa_status = fa.group(2).lower()
        start = int(ym.group(1))
        out.append(
            SpotracContract(
                start_year=start,
                end_year=int(ym.group(2)),
                first_season=season_label(start),
                type_label=type_label,
                is_current="current" in statuses,
                is_upcoming="upcoming extension" in statuses or "pending" in statuses,
                years=int(yrs.group(1)) if yrs else None,
                total_value=_money(terms),
                aav=_money(cells.get("average salary")),
                gtd_at_sign=_money(cells.get("gtd at sign")),
                total_gtd=_money(cells.get("total gtd")),
                signed_using=normalize_signed_using(cells.get("signed using")),
                fa_year=fa_year,
                fa_status=fa_status,
            )
        )
    return out
