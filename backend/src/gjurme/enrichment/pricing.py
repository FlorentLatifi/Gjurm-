"""LLM price table and cost arithmetic.

Prices are USD per million tokens (first-party Anthropic API), last checked 2026-09-24 against
Anthropic's published model table. Re-verify at https://www.anthropic.com/pricing before changing
budgets. Unknown models are priced at the most expensive known rate so that a typo in
``LLM_MODEL`` can never make the budget guard *under*-estimate spend.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

PRICES_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    # model: (input, output)
    "claude-fable-5-1": (Decimal("10.00"), Decimal("50.00")),
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00")),
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    "claude-opus-4-8": (Decimal("5.00"), Decimal("25.00")),
    "claude-sonnet-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-sonnet-4-6": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
    "fake": (Decimal("0"), Decimal("0")),
}
FALLBACK_PRICE = max(PRICES_PER_MTOK.values())
CACHE_WRITE_MULTIPLIER = Decimal("1.25")  # 5-minute TTL cache writes
CACHE_READ_MULTIPLIER = Decimal("0.10")
MTOK = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def register_price(model: str, input_per_mtok: float, output_per_mtok: float) -> None:
    """Price a model that is not in the table (OpenAI-compatible provider: local or free tier).

    Known models keep their published price, so a misconfigured override can never make the
    budget guard under-estimate Claude.
    """
    if model in PRICES_PER_MTOK:
        return
    PRICES_PER_MTOK[model] = (Decimal(str(input_per_mtok)), Decimal(str(output_per_mtok)))


def price_for(model: str) -> tuple[Decimal, Decimal]:
    return PRICES_PER_MTOK.get(model, FALLBACK_PRICE)


def cost_usd(model: str, usage: Usage) -> Decimal:
    price_in, price_out = price_for(model)
    total = (
        Decimal(usage.input_tokens) * price_in
        + Decimal(usage.cache_write_tokens) * price_in * CACHE_WRITE_MULTIPLIER
        + Decimal(usage.cache_read_tokens) * price_in * CACHE_READ_MULTIPLIER
        + Decimal(usage.output_tokens) * price_out
    ) / MTOK
    return total.quantize(Decimal("0.000001"))


def estimate_call_cost(
    model: str, input_chars: int, system_tokens: int, max_output_tokens: int
) -> Decimal:
    """Pessimistic pre-call estimate used for budget reservation.

    Assumes a cache *write* for the system prompt (the most expensive case), ~3 characters per
    token for Albanian text, and the full ``max_output_tokens``. Actual cost is settled from the
    API's usage report after the call.
    """
    return cost_usd(
        model,
        Usage(
            input_tokens=input_chars // 3 + 60,
            cache_write_tokens=system_tokens,
            output_tokens=max_output_tokens,
        ),
    )
