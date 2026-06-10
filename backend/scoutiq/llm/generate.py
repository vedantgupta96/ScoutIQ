"""Grounded rationale generation: fuse the model's value gap with the scouting signal into a cited verdict.

Live Claude call (captures token usage for costing). `multi_source` mode first gathers N angle-varied
Sonar reports; `fusion` mode uses whatever narratives the caller already has (the cached scout report).
A deterministic grounding guard checks the verdict states the correct over/underpaid direction and cites
at least one source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import requests

from scoutiq.llm.extract import ANTHROPIC_MESSAGES_URL, ANTHROPIC_VERSION
from scoutiq.llm.pricing import Usage, estimate_cost
from scoutiq.sources import sonar

# Angle prompts used to elicit independent Sonar perspectives in multi_source mode.
MULTI_SOURCE_ANGLES = [
    "offensive skill, shot-making, and scoring role",
    "defense, motor, and physical tools",
    "leadership, intangibles, durability, and locker-room fit",
]

SYSTEM_PROMPT = (
    "You are an NBA front-office analyst. In <=120 words, write a grounded verdict on whether a player "
    "is overpaid or underpaid, FUSING two independent signals: (1) the quantitative model's "
    "production-implied value gap, and (2) the qualitative scouting reports. Rules: ground every claim in "
    "the data provided; the over/underpaid direction MUST match the sign of the value gap (positive gap = "
    "underpaid/bargain, negative = overpaid); reference specific scouting traits; explicitly note where "
    "the model and the scouting AGREE or DISAGREE; never invent statistics or dollar figures beyond those "
    "given; cite sources inline as [1], [2] using the numbered Sources list. Plain prose only — no "
    "markdown, asterisks, or headings."
)


@dataclass
class RationaleInputs:
    player_name: str
    season: str
    value_pct: float | None
    actual_pct: float | None
    gap_pct: float | None
    verdict_label: str | None
    caution_flags: list[str]
    contract_summary: str | None
    traits: list[tuple[str, float, str]]   # (trait, avg_score, evidence)
    narratives: list[str]
    citations: list[str]


@dataclass
class RationaleResult:
    text: str
    citations: list[str]
    input_tokens: int
    output_tokens: int
    est_cost_usd: float          # Claude + Sonar combined
    sonar_cost_usd: float
    grounding_issues: list[str] = field(default_factory=list)


def gather_multi_source(player_id: int, player_name: str, season: str, n: int) -> tuple[list[str], list[str], Usage]:
    """Fetch up to n angle-varied Sonar reports; return (narratives, deduped citations, total usage)."""
    narratives: list[str] = []
    citations: list[str] = []
    usage = Usage(0, 0)
    for angle in MULTI_SOURCE_ANGLES[:n]:
        report = sonar.fetch_scout_report(player_id, player_name, season, angle=angle)
        if report is None:
            continue
        narratives.append(report.source_text)
        citations.extend(report.citations)
        usage = usage + Usage(report.input_tokens, report.output_tokens)
    deduped = list(dict.fromkeys(c for c in citations if c))
    return narratives, deduped, usage


def _build_user_prompt(inp: RationaleInputs) -> str:
    def pct(v: float | None) -> str:
        return f"{v:.1f}% of cap" if v is not None else "n/a"

    gap_str = "n/a"
    if inp.gap_pct is not None:
        direction = "underpaid (bargain)" if inp.gap_pct >= 0 else "overpaid"
        gap_str = f"{inp.gap_pct:+.1f}% of cap -> {direction}"

    traits = "\n".join(f"- {t}: {s:.1f}/5 (e.g. \"{ev}\")" for t, s, ev in inp.traits) or "- (none)"
    sources = "\n".join(f"[{i + 1}] {url}" for i, url in enumerate(inp.citations)) or "(no sources)"
    narratives = "\n\n".join(f"Report {i + 1}: {n}" for i, n in enumerate(inp.narratives)) or "(no narrative)"

    return (
        f"Player: {inp.player_name} ({inp.season})\n"
        f"MODEL — production-implied value: {pct(inp.value_pct)}; actual pay: {pct(inp.actual_pct)}; "
        f"value gap: {gap_str}; verdict: {inp.verdict_label or 'n/a'}; "
        f"cautions: {', '.join(inp.caution_flags) or 'none'}\n"
        f"CONTRACT: {inp.contract_summary or 'n/a'}\n"
        f"SCOUTING TRAITS (1-5):\n{traits}\n"
        f"SCOUTING NARRATIVE(S):\n{narratives}\n"
        f"SOURCES:\n{sources}\n"
    )


def _call_claude(system: str, user: str, *, api_key: str, model: str) -> tuple[str, Usage]:
    payload = {
        "model": model,
        "max_tokens": 400,
        "temperature": 0.3,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    response = requests.post(
        ANTHROPIC_MESSAGES_URL,
        headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"},
        json=payload,
        timeout=45,
    )
    response.raise_for_status()
    body = response.json()
    text = "".join(p.get("text", "") for p in body.get("content", []) if p.get("type") == "text").strip()
    u = body.get("usage") or {}
    return text, Usage(int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0))


def check_grounding(text: str, gap_pct: float | None, citations: list[str]) -> list[str]:
    """Cheap, deterministic guard: correct over/underpaid direction + at least one citation."""
    issues: list[str] = []
    low = text.lower()
    if gap_pct is not None:
        if gap_pct >= 1 and not ("underpaid" in low or "bargain" in low):
            issues.append("expected an underpaid/bargain verdict for a positive value gap")
        if gap_pct <= -1 and "overpaid" not in low:
            issues.append("expected an overpaid verdict for a negative value gap")
    if citations and not re.search(r"\[\d+\]", text):
        issues.append("no inline [n] citation despite available sources")
    return issues


def generate_rationale(
    inputs: RationaleInputs,
    *,
    api_key: str,
    model: str,
    sonar_usage: Usage | None = None,
) -> RationaleResult:
    """Generate a cited rationale via Claude and run the grounding guard. `sonar_usage` is the token
    usage already spent gathering narratives (multi_source); folded into the total cost."""
    text, claude_usage = _call_claude(SYSTEM_PROMPT, _build_user_prompt(inputs), api_key=api_key, model=model)
    sonar_usage = sonar_usage or Usage(0, 0)
    sonar_cost = estimate_cost(sonar_usage, "sonar")
    total_cost = round(estimate_cost(claude_usage, model) + sonar_cost, 6)
    return RationaleResult(
        text=text,
        citations=inputs.citations,
        input_tokens=claude_usage.input_tokens,
        output_tokens=claude_usage.output_tokens,
        est_cost_usd=total_cost,
        sonar_cost_usd=sonar_cost,
        grounding_issues=check_grounding(text, inputs.gap_pct, inputs.citations),
    )
