"""Baseline 2: Z-score on error_rate.

For each service, computes Z-score of error_rate during the fault window
vs the baseline window (stored in snapshot as is_baseline=True entries).
Ranks services by Z-score. Always predicts 'high_latency' as fault type.

Tests whether service localization alone (without fault type) is achievable
with a simple statistical heuristic.
"""

from __future__ import annotations

import numpy as np

from src.agent.schemas import InvestigationReport, RootCauseHypothesis
from src.datasources.live import ASTRONOMY_SHOP_SERVICES
from src.datasources.protocol import DataSource
from src.telemetry_queries import METRIC_QUERIES

_ERROR_RATE_TPL = METRIC_QUERIES["error_rate"]


class ZScoreBaseline:
    """Ranks services by Z-score of error_rate. Fault type always 'high_latency'."""

    def predict(
        self,
        ds: DataSource,
        start: str,
        end: str,
        namespace: str,
        scenario_id: str,
    ) -> InvestigationReport:
        scores: dict[str, float] = {}

        for svc in ASTRONOMY_SHOP_SERVICES:
            query = _ERROR_RATE_TPL.format(svc=svc)

            fault_series = ds.query_prometheus_range(query, start, end)
            # Baseline window: subtract 30 min from start
            baseline_start = _subtract_minutes(start, 30)
            baseline_series = ds.query_prometheus_range(query, baseline_start, start)

            fault_values = _extract_values(fault_series)
            baseline_values = _extract_values(baseline_series)

            if not fault_values or not baseline_values:
                scores[svc] = 0.0
                continue

            mu = float(np.mean(baseline_values))
            sigma = float(np.std(baseline_values)) + 1e-9
            fault_mean = float(np.mean(fault_values))
            z = (fault_mean - mu) / sigma
            scores[svc] = max(0.0, z)

        ranked = sorted(scores.items(), key=lambda x: -x[1])
        top3 = ranked[:3]

        return InvestigationReport(
            incident_id=scenario_id,
            investigation_start_ts=start,
            investigation_end_ts=end,
            root_causes=[
                RootCauseHypothesis(
                    rank=i + 1,
                    service=svc,
                    fault_type="high_latency",  # always predicts this
                    description=f"Z-score heuristic: error_rate z-score={z:.2f}",
                    confidence=min(1.0, z / 10.0),
                    evidence=[],
                )
                for i, (svc, z) in enumerate(top3)
            ],
            remediation_steps=[],
            fault_type_classification="high_latency",
            grounding_score=0.0,
            latency_s=0.0,
            cost_usd=0.0,
            llm_model="zscore_baseline",
        )


def _extract_values(series: list[dict[str, object]]) -> list[float]:
    values: list[float] = []
    for s in series:
        for _ts, val in s.get("values", []):
            try:
                v = float(val)
                if not (v != v):  # skip NaN
                    values.append(v)
            except (ValueError, TypeError):
                pass
    return values


def _subtract_minutes(iso_ts: str, minutes: int) -> str:
    from datetime import datetime, timedelta
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (dt - timedelta(minutes=minutes)).isoformat()
