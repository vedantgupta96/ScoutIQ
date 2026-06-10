"""Token pricing + cost estimation for the rationale layer.

Prices are USD per 1,000,000 tokens. Claude prices verified via the claude-api skill
(claude-sonnet-4-6: $3.00 in / $15.00 out). Perplexity Sonar prices are approximate and
configurable — update PRICES if Perplexity changes its rates.
"""
from __future__ import annotations

from dataclasses import dataclass

# USD per 1M tokens: (input, output)
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "sonar": (1.00, 1.00),       # Perplexity Sonar — approximate; per-1M tokens
    "sonar-pro": (3.00, 15.00),
}

# Fallback when a model id is unknown — Sonnet-tier, so estimates skew high not low.
_DEFAULT = (3.00, 15.00)


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens)


def estimate_cost(usage: Usage, model: str) -> float:
    """USD cost of one call's token usage for `model`, rounded to 6 decimals."""
    in_price, out_price = PRICES.get(model, _DEFAULT)
    cost = usage.input_tokens / 1_000_000 * in_price + usage.output_tokens / 1_000_000 * out_price
    return round(cost, 6)
