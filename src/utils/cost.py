"""LLM cost estimation from token counts.

Pricing switched to deepseek-flash real rates (batch-1 COST-01 fix; previously the
llama-3.1-70b-instruct NIM approximation, which over-stated costs ~2.3x on input).

Source: https://api-docs.deepseek.com/quick_start/pricing (official rate card,
verified 2026-09-18, effective 2026-09-10):
  - input (cache miss):  off-peak $0.15 / 1M, peak $0.30 / 1M
  - input (cache hit):   off-peak $0.006 / 1M (not modeled — we conservatively
                          bill all input at the cache-miss rate)
  - output:              off-peak $0.60 / 1M, peak $1.20 / 1M
Peak hours: Mon–Fri 01:00–04:00 & 06:00–10:00 UTC (= Beijing 09:00–12:00 & 14:00–18:00).
We use the off-peak rate as the standing convention (same relativity across runs).
"""

from __future__ import annotations

# deepseek-flash (DeepSeek-V4.1-Flash) official prices per 1M tokens (USD, off-peak)
_INPUT_PRICE_PER_1M = 0.15
_OUTPUT_PRICE_PER_1M = 0.60


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Return estimated USD cost for a single LLM call."""
    return (
        prompt_tokens / 1_000_000 * _INPUT_PRICE_PER_1M
        + completion_tokens / 1_000_000 * _OUTPUT_PRICE_PER_1M
    )
