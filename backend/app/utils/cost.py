"""
Phase 14 — Centralized LLM Cost Calculation.

All pricing lives in app.config.LLM_PRICING.
This module provides one function: calculate_llm_cost().

Rules:
  - Returns None (never fabricates) when tokens or pricing is unavailable.
  - Pricing is looked up by model name; partial matches (prefix) are tried
    so "gemini-2.0-flash-001" matches "gemini-2.0-flash".
  - Never hardcodes pricing values — always reads from config.LLM_PRICING.
"""

from __future__ import annotations

from app.config import LLM_PRICING


def calculate_llm_cost(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    """
    Calculate the estimated USD cost for a single Gemini API call.

    Args:
        model:         Gemini model name (e.g. 'gemini-flash-latest').
        input_tokens:  Number of prompt tokens (None → return None).
        output_tokens: Number of completion tokens (None → return None).

    Returns:
        Estimated cost in USD, or None if tokens/pricing unavailable.
        Never returns a fabricated value.
    """
    if input_tokens is None or output_tokens is None:
        return None

    pricing = _lookup_pricing(model)
    if pricing is None:
        return None

    cost = (
        (input_tokens  / 1_000) * pricing["input"]  +
        (output_tokens / 1_000) * pricing["output"]
    )
    return round(cost, 8)


def _lookup_pricing(model: str) -> dict[str, float] | None:
    """
    Look up model pricing from LLM_PRICING.

    Tries exact match first, then prefix match, to handle versioned
    model names like 'gemini-2.0-flash-001' → 'gemini-2.0-flash'.
    """
    if not model:
        return None

    # 1. Exact match
    if model in LLM_PRICING:
        return LLM_PRICING[model]

    # 2. Prefix match — longest matching prefix wins
    best_key = None
    best_len = 0
    for key in LLM_PRICING:
        if model.startswith(key) and len(key) > best_len:
            best_key = key
            best_len = len(key)

    return LLM_PRICING[best_key] if best_key else None


def estimate_review_cost(llm_usage_rows: list[dict]) -> float | None:
    """
    Sum the estimated costs from a list of llm_usage DB rows.

    Args:
        llm_usage_rows: List of dicts with keys: model, input_tokens,
                        output_tokens, estimated_cost.

    Returns:
        Total cost in USD, or None if no cost data is available.
    """
    total = 0.0
    any_cost = False

    for row in llm_usage_rows:
        cost = row.get("estimated_cost")
        if cost is not None:
            total += float(cost)
            any_cost = True
        else:
            # Try calculating from tokens if estimated_cost not stored
            computed = calculate_llm_cost(
                model=row.get("model", ""),
                input_tokens=row.get("input_tokens"),
                output_tokens=row.get("output_tokens"),
            )
            if computed is not None:
                total += computed
                any_cost = True

    return round(total, 8) if any_cost else None
