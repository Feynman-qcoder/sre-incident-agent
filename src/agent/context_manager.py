"""Context compression pipeline — keeps telemetry within the LLM context budget.

Three layers:
  Layer 1: Query-time limits (enforced at tool call level, not here)
  Layer 2: Statistical summarization (time-series → compact summary dict)
  Layer 3: Budget counter (truncate if accumulated context exceeds threshold)
"""

from __future__ import annotations

import json
import os

import numpy as np
import structlog

log = structlog.get_logger()

CONTEXT_BUDGET_TOKENS = int(os.getenv("CONTEXT_BUDGET_TOKENS", "28000"))


def compress_prometheus_range(
    results: list[dict[str, object]],
    query: str,
) -> str:
    """Layer 2: Convert a list of time-series into a compact summary string.

    Each series → {service_labels, mean, p50, p95, p99, max, anomaly_start, anomaly_end}
    """
    if not results:
        return f"[no data for: {query[:80]}]"

    summaries: list[str] = []
    for series in results:
        metric_labels = series.get("metric", {})
        values_raw: list[list[object]] = series.get("values", [])  # type: ignore[assignment]
        if not values_raw:
            continue
        floats = [float(v[1]) for v in values_raw if v[1] not in ("NaN", "+Inf", "-Inf", None)]
        if not floats:
            continue
        arr = np.array(floats)
        mean_v = float(np.mean(arr))
        p50 = float(np.percentile(arr, 50))
        p95 = float(np.percentile(arr, 95))
        p99 = float(np.percentile(arr, 99))
        max_v = float(np.max(arr))

        # Find anomaly window: contiguous region where value > 3 * mean (or > 0.5 for rates)
        threshold = max(3.0 * mean_v, 0.1) if mean_v > 0 else 0.1
        anomaly_idxs = [i for i, v in enumerate(floats) if v > threshold]
        if anomaly_idxs and values_raw:
            ts_start = values_raw[anomaly_idxs[0]][0]
            ts_end = values_raw[anomaly_idxs[-1]][0]
            anomaly = f"anomaly [{ts_start}→{ts_end}]"
        else:
            anomaly = "no anomaly detected"

        label_str = json.dumps(metric_labels, separators=(",", ":"))
        summaries.append(
            f"  {label_str}: mean={mean_v:.3f} p50={p50:.3f} p95={p95:.3f} "
            f"p99={p99:.3f} max={max_v:.3f} | {anomaly}"
        )

    return f"PromQL: {query[:100]}\n" + "\n".join(summaries)


def compress_traces(traces: list[dict[str, object]]) -> str:
    """Layer 2: Summarize trace list into compact text."""
    if not traces:
        return "[no traces found]"

    total = len(traces)
    error_count = sum(1 for t in traces if t.get("hasError"))
    durations = [int(t.get("durationMs", 0)) for t in traces]
    p95_dur = int(np.percentile(durations, 95)) if durations else 0

    # Include first 3 trace IDs + their error status
    examples = []
    for t in traces[:3]:
        tid = t.get("traceID", "?")[:16]
        dur = t.get("durationMs", "?")
        err = "ERROR" if t.get("hasError") else "ok"
        root = t.get("rootTraceName", "")[:40]
        examples.append(f"    {tid}: {root} | {dur}ms | {err}")

    return (
        f"Traces: {total} total, {error_count} with errors, p95_duration={p95_dur}ms\n"
        + "\n".join(examples)
    )


def compress_loki(results: list[dict[str, object]]) -> str:
    """Layer 2: Deduplicate and summarize Loki log results.

    Deduplicates by first 100 chars of each log line, keeps max 5 unique error patterns.
    """
    if not results:
        return "[no logs found]"

    counts: dict[str, int] = {"error": 0, "warn": 0, "info": 0, "other": 0}
    unique_patterns: dict[str, str] = {}  # prefix → full line

    for stream_result in results:
        values: list[list[str]] = stream_result.get("values", [])  # type: ignore[assignment]
        for _ts, line in values:
            lower = line.lower()
            if "error" in lower:
                counts["error"] += 1
            elif "warn" in lower:
                counts["warn"] += 1
            elif "info" in lower:
                counts["info"] += 1
            else:
                counts["other"] += 1

            # Deduplicate by first 100 chars
            prefix = line[:100]
            if prefix not in unique_patterns and "error" in lower:
                unique_patterns[prefix] = line[:200]
                if len(unique_patterns) >= 5:
                    break

    count_str = " | ".join(f"{k}={v}" for k, v in counts.items() if v > 0)
    lines = [f"Log counts: {count_str}", "Top error patterns:"]
    for line in list(unique_patterns.values())[:5]:
        lines.append(f"  {line}")

    return "\n".join(lines)


class ContextBudget:
    """Layer 3: Tracks accumulated token budget for a single investigation."""

    def __init__(self, budget: int = CONTEXT_BUDGET_TOKENS) -> None:
        self._budget = budget
        self._used = 0

    def remaining(self) -> int:
        return max(0, self._budget - self._used)

    def consume(self, text: str) -> str:
        """Account for text tokens. If over budget, truncate and annotate."""
        estimated = len(text) // 4  # rough token estimate
        if self._used + estimated > self._budget:
            # Truncate to remaining budget
            max_chars = self.remaining() * 4
            if max_chars < 100:
                return "[TRUNCATED: context budget exhausted]"
            truncated = text[:max_chars]
            log.warning("context_budget_truncated", used=self._used, budget=self._budget)
            self._used = self._budget
            return truncated + f"\n[TRUNCATED: context budget exhausted after {max_chars} chars]"
        self._used += estimated
        return text

    @property
    def used_tokens(self) -> int:
        return self._used
