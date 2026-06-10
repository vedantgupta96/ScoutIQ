"""Unit tests for the grounded-rationale layer (pricing, grounding guard, generation). No live HTTP."""
from scoutiq.llm import generate
from scoutiq.llm.pricing import Usage, estimate_cost


def test_estimate_cost_uses_per_million_pricing():
    # claude-sonnet-4-6 = $3 in / $15 out per 1M tokens
    cost = estimate_cost(Usage(1_000_000, 1_000_000), "claude-sonnet-4-6")
    assert cost == 18.0
    assert estimate_cost(Usage(500_000, 0), "claude-sonnet-4-6") == 1.5


def test_usage_adds():
    assert (Usage(10, 5) + Usage(3, 2)) == Usage(13, 7)


def test_grounding_guard_flags_wrong_direction():
    # positive gap = underpaid; a verdict that says "overpaid" is wrong
    issues = generate.check_grounding("This player looks overpaid.", gap_pct=6.0, citations=["http://x"])
    assert any("underpaid" in i for i in issues)


def test_grounding_guard_flags_missing_citation():
    issues = generate.check_grounding("A clear bargain and underpaid.", gap_pct=6.0, citations=["http://x"])
    assert any("citation" in i for i in issues)


def test_grounding_guard_passes_clean_rationale():
    text = "A clear bargain — underpaid relative to production [1]."
    assert generate.check_grounding(text, gap_pct=6.0, citations=["http://x"]) == []


def _inputs(gap):
    return generate.RationaleInputs(
        player_name="Test Player", season="2025-26", value_pct=28.0, actual_pct=18.0, gap_pct=gap,
        verdict_label="Bargain", caution_flags=[], contract_summary="4yr / $100.0M from 2025-26",
        traits=[("basketball_iq", 4.5, "reads the floor")], narratives=["Elite processor."],
        citations=["https://espn.com/x"],
    )


def test_generate_rationale_parses_usage_and_costs(monkeypatch):
    body = {
        "content": [{"type": "text", "text": "Underpaid bargain; model and scouts agree [1]."}],
        "usage": {"input_tokens": 600, "output_tokens": 120},
    }

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return body

    monkeypatch.setattr(generate.requests, "post", lambda *a, **k: _Resp())

    result = generate.generate_rationale(
        _inputs(10.0), api_key="k", model="claude-sonnet-4-6", sonar_usage=Usage(2000, 400),
    )

    assert result.input_tokens == 600 and result.output_tokens == 120
    assert "underpaid" in result.text.lower()
    assert result.grounding_issues == []
    # claude: 600/1e6*3 + 120/1e6*15 = 0.0018+0.0018 = 0.0036; sonar: 2000/1e6*1 + 400/1e6*1 = 0.0024
    assert result.sonar_cost_usd == 0.0024
    assert result.est_cost_usd == round(0.0036 + 0.0024, 6)


def test_build_user_prompt_states_direction():
    prompt = generate._build_user_prompt(_inputs(-7.0))
    assert "overpaid" in prompt
    prompt_up = generate._build_user_prompt(_inputs(7.0))
    assert "underpaid" in prompt_up
