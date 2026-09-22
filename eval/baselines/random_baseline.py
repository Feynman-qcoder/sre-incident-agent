"""Baseline 1: Random — random service and fault type selection.

Establishes the performance floor. Expected Accuracy@1 ≈ 1/(7×5) = 2.9%.
"""

from __future__ import annotations

import random

from src.agent.schemas import InvestigationReport, RootCauseHypothesis
from src.datasources.live import ASTRONOMY_SHOP_SERVICES

_FAULT_TYPES = ["pod_crash", "high_latency", "cpu_stress", "memory_stress", "http_abort"]


class RandomBaseline:
    """Predicts random services and fault types, reproducibly seeded."""

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed

    def predict(
        self,
        ds: object,
        start: str,
        end: str,
        namespace: str,
        scenario_id: str,
    ) -> InvestigationReport:
        rng = random.Random(self._seed)
        sampled_services = rng.sample(ASTRONOMY_SHOP_SERVICES, k=min(3, len(ASTRONOMY_SHOP_SERVICES)))
        top_fault = rng.choice(_FAULT_TYPES)

        return InvestigationReport(
            incident_id=scenario_id,
            investigation_start_ts=start,
            investigation_end_ts=end,
            root_causes=[
                RootCauseHypothesis(
                    rank=i + 1,
                    service=sampled_services[i],
                    fault_type=rng.choice(_FAULT_TYPES),
                    description="Random baseline prediction",
                    confidence=rng.uniform(0.1, 0.9),
                    evidence=[],
                )
                for i in range(3)
            ],
            remediation_steps=[],
            fault_type_classification=top_fault,
            grounding_score=0.0,
            latency_s=0.0,
            cost_usd=0.0,
            llm_model="random_baseline",
        )
