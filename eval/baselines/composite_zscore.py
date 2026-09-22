"""Baseline 3: Composite Z-score over 4 signals.

For each service: Z-scores of error_rate, p99_latency, cpu_usage, memory_usage.
composite_score = max(z_err, z_lat, z_cpu, z_mem).
Fault type is inferred from the dominant signal.

This is the strongest non-LLM baseline. The agent must beat it to justify LLM cost.
"""

from __future__ import annotations

import numpy as np

from src.agent.schemas import InvestigationReport, RootCauseHypothesis
from src.datasources.live import ASTRONOMY_SHOP_SERVICES
from src.datasources.protocol import DataSource
from src.telemetry_queries import METRIC_QUERIES, SIGNAL_TO_FAULT

# Five anomaly signals (request_rate is excluded — it is not an anomaly direction on its own).
_SIGNALS = ["error_rate", "p99_latency_ms", "cpu_usage", "memory_usage", "pod_restarts"]
_QUERIES = {k: METRIC_QUERIES[k] for k in _SIGNALS}

# Signal → fault_type mapping (canonical, includes pod_restarts → pod_crash).
_SIGNAL_TO_FAULT = SIGNAL_TO_FAULT


class CompositeZScoreBaseline:
    """Ranks services by max Z-score across 4 signals. Infers fault type from dominant signal."""

    def predict(
        self,
        ds: DataSource,
        start: str,
        end: str,
        namespace: str,
        scenario_id: str,
    ) -> InvestigationReport:
        baseline_start = _subtract_minutes(start, 30)

        composite_scores: dict[str, float] = {}
        dominant_signals: dict[str, str] = {}

        for svc in ASTRONOMY_SHOP_SERVICES:
            signal_zscores: dict[str, float] = {}

            for signal_name, tpl in _QUERIES.items():
                query = tpl.format(svc=svc)
                fault_series = ds.query_prometheus_range(query, start, end)
                baseline_series = ds.query_prometheus_range(query, baseline_start, start)

                fault_vals = _extract_values(fault_series)
                baseline_vals = _extract_values(baseline_series)

                if not fault_vals or not baseline_vals:
                    signal_zscores[signal_name] = 0.0
                    continue

                mu = float(np.mean(baseline_vals))
                sigma = float(np.std(baseline_vals)) + 1e-9
                z = (float(np.mean(fault_vals)) - mu) / sigma
                signal_zscores[signal_name] = max(0.0, z)

            if signal_zscores:
                best_signal = max(signal_zscores, key=lambda k: signal_zscores[k])
                composite_scores[svc] = signal_zscores[best_signal]
                dominant_signals[svc] = best_signal
            else:
                composite_scores[svc] = 0.0
                dominant_signals[svc] = "error_rate"

        ranked = sorted(composite_scores.items(), key=lambda x: -x[1])
        top3 = ranked[:3]

        # Top-1 fault type from dominant signal of top service
        top_service = top3[0][0] if top3 else ASTRONOMY_SHOP_SERVICES[0]
        top_fault = _SIGNAL_TO_FAULT[dominant_signals.get(top_service, "error_rate")]

        return InvestigationReport(
            incident_id=scenario_id,
            investigation_start_ts=start,
            investigation_end_ts=end,
            root_causes=[
                RootCauseHypothesis(
                    rank=i + 1,
                    service=svc,
                    fault_type=_SIGNAL_TO_FAULT[dominant_signals.get(svc, "error_rate")],
                    description=(
                        f"Composite Z-score: dominant_signal={dominant_signals.get(svc,'?')}"
                        f" z={z:.2f}"
                    ),
                    confidence=min(1.0, z / 10.0),
                    evidence=[],
                )
                for i, (svc, z) in enumerate(top3)
            ],
            remediation_steps=[],
            fault_type_classification=top_fault,
            grounding_score=0.0,
            latency_s=0.0,
            cost_usd=0.0,
            llm_model="composite_zscore_baseline",
        )


def _extract_values(series: list[dict[str, object]]) -> list[float]:
    values: list[float] = []
    for s in series:
        for _ts, val in s.get("values", []):
            try:
                v = float(val)
                if not (v != v):
                    values.append(v)
            except (ValueError, TypeError):
                pass
    return values


def _subtract_minutes(iso_ts: str, minutes: int) -> str:
    from datetime import datetime, timedelta
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (dt - timedelta(minutes=minutes)).isoformat()
