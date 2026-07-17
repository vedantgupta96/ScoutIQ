"""Deterministic two-team salary-matching rules for the Trade lab."""
from __future__ import annotations

from dataclasses import dataclass

BASE_CAP = 140_588_000
BASE_EXPANDED_FIXED = 7_752_000


@dataclass(frozen=True)
class MatchResult:
    status: str
    method: str | None
    rule_label: str
    incoming: int
    outgoing: int
    allowed_incoming: int
    margin: int
    reasons: list[str]


def expanded_fixed_amount(salary_cap: int) -> int:
    return round(BASE_EXPANDED_FIXED * salary_cap / BASE_CAP)


def salary_match(
    *, outgoing: int, incoming: int, payroll_before: int, outgoing_count: int,
    salary_cap: int, first_apron: int, second_apron: int,
) -> MatchResult:
    if outgoing <= 0 or incoming <= 0:
        return MatchResult("incomplete", None, "Incomplete package", incoming, outgoing, 0, -incoming,
                           ["Select players on both sides."])
    post = payroll_before - outgoing + incoming
    allowance = 0 if post > first_apron else 250_000
    if outgoing_count >= 2 and post > second_apron:
        return MatchResult("needs-review", None, "Non-aggregated allocation required", incoming,
                           outgoing, outgoing, outgoing - incoming,
                           ["Aggregating two or more outgoing salaries above the second apron is not modeled."])
    paths: list[tuple[str, str, int]] = []
    room = max(0, salary_cap - (payroll_before - outgoing)) + allowance
    if post <= salary_cap + allowance:
        paths.append(("cap-room", "Cap-room path", room))
    standard = outgoing + allowance
    standard_method = "aggregated-standard-tpe" if outgoing_count >= 2 else "standard-tpe"
    standard_label = "Aggregated Standard TPE" if outgoing_count >= 2 else "Standard TPE"
    paths.append((standard_method, standard_label, standard))
    if post <= first_apron:
        fixed = expanded_fixed_amount(salary_cap)
        expanded = max(min(2 * outgoing + allowance, outgoing + fixed), round(1.25 * outgoing) + allowance)
        paths.append(("expanded-tpe", "Expanded TPE", expanded))
    passing = [path for path in paths if incoming <= path[2]]
    chosen = min(passing, key=lambda path: path[2]) if passing else max(paths, key=lambda path: path[2])
    status = "pass" if passing else "fail"
    reason = (f"Incoming salary is ${chosen[2] - incoming:,} below the modeled limit."
              if passing else f"Incoming salary exceeds the closest modeled limit by ${incoming - chosen[2]:,}.")
    return MatchResult(status, chosen[0], chosen[1], incoming, outgoing, chosen[2],
                       chosen[2] - incoming, [reason])


def overall_status(a: str, b: str) -> str:
    if "incomplete" in (a, b):
        return "incomplete"
    if "needs-review" in (a, b):
        return "needs-review"
    if "fail" in (a, b):
        return "modeled-noncompliant"
    return "modeled-compliant"
