"""Evaluation metrics for root-cause analysis quality.

All metrics operate on lists of (InvestigationReport, ground_truth_dict) pairs.
Metrics are never self-reported by the agent — this module is the single source of truth.

Metrics:
  accuracy_at_k(k)   — fraction where correct (service, fault_type) is in top-k
  mrr                — mean reciprocal rank of correct hypothesis
  fault_type_accuracy — fraction where top-1 fault_type matches ground truth
  mean_latency_s     — mean wall-clock investigation latency
  total_cost_usd     — total cost across all scenarios
"""

from __future__ import annotations

from dataclasses import dataclass

from src.agent.schemas import InvestigationReport


@dataclass
class EvalMetrics:
    n_scenarios: int
    accuracy_at_1: float
    accuracy_at_3: float
    mrr: float
    fault_type_accuracy: float
    mean_grounding_score: float
    mean_latency_s: float
    total_cost_usd: float
    mean_cost_usd: float

    def as_dict(self) -> dict[str, object]:
        return {
            "n_scenarios": self.n_scenarios,
            "accuracy_at_1": round(self.accuracy_at_1, 4),
            "accuracy_at_3": round(self.accuracy_at_3, 4),
            "mrr": round(self.mrr, 4),
            "fault_type_accuracy": round(self.fault_type_accuracy, 4),
            "mean_grounding_score": round(self.mean_grounding_score, 4),
            "mean_latency_s": round(self.mean_latency_s, 2),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "mean_cost_usd": round(self.mean_cost_usd, 6),
        }


@dataclass
class ScenarioResult:
    scenario_id: str
    report: InvestigationReport
    ground_truth: dict[str, str]
    grounding_score: float   # injected by harness after grounding_verifier.verify()


def compute_metrics(results: list[ScenarioResult]) -> EvalMetrics:
    """Compute all evaluation metrics over a list of scenario results."""
    if not results:
        return EvalMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    n = len(results)
    acc1_sum = 0.0
    acc3_sum = 0.0
    mrr_sum = 0.0
    fault_type_sum = 0.0
    grounding_sum = 0.0
    latency_sum = 0.0
    cost_sum = 0.0

    for sr in results:
        gt_service = sr.ground_truth.get("fault_service", "")
        gt_fault = sr.ground_truth.get("fault_type", "")
        rc = sr.report.root_causes

        # Accuracy@1: both service AND fault_type match rank-1
        if rc and rc[0].service == gt_service and rc[0].fault_type == gt_fault:
            acc1_sum += 1.0

        # Accuracy@3: correct (service, fault_type) pair anywhere in top-3
        for h in rc[:3]:
            if h.service == gt_service and h.fault_type == gt_fault:
                acc3_sum += 1.0
                break

        # MRR: 1/rank_i of first correct hypothesis (0 if not found)
        for i, h in enumerate(rc[:3]):
            if h.service == gt_service and h.fault_type == gt_fault:
                mrr_sum += 1.0 / (i + 1)
                break

        # Fault type accuracy: only top-1 fault_type must match (service agnostic)
        if rc and rc[0].fault_type == gt_fault:
            fault_type_sum += 1.0

        grounding_sum += sr.grounding_score
        latency_sum += sr.report.latency_s
        cost_sum += sr.report.cost_usd

    return EvalMetrics(
        n_scenarios=n,
        accuracy_at_1=acc1_sum / n,
        accuracy_at_3=acc3_sum / n,
        mrr=mrr_sum / n,
        fault_type_accuracy=fault_type_sum / n,
        mean_grounding_score=grounding_sum / n,
        mean_latency_s=latency_sum / n,
        total_cost_usd=cost_sum,
        mean_cost_usd=cost_sum / n,
    )


def compute_per_scenario(sr: ScenarioResult) -> dict[str, object]:
    """Compute per-scenario metrics for detailed artifact logging."""
    gt_service = sr.ground_truth.get("fault_service", "")
    gt_fault = sr.ground_truth.get("fault_type", "")
    rc = sr.report.root_causes

    rank = None
    for i, h in enumerate(rc[:3]):
        if h.service == gt_service and h.fault_type == gt_fault:
            rank = i + 1
            break

    return {
        "scenario_id": sr.scenario_id,
        "ground_truth_service": gt_service,
        "ground_truth_fault_type": gt_fault,
        "predicted_service": rc[0].service if rc else "none",
        "predicted_fault_type": rc[0].fault_type if rc else "unknown",
        "accuracy_at_1": 1 if rank == 1 else 0,
        "accuracy_at_3": 1 if rank is not None else 0,
        "mrr": 1.0 / rank if rank else 0.0,
        "fault_type_correct": 1 if rc and rc[0].fault_type == gt_fault else 0,
        "grounding_score": sr.grounding_score,
        "latency_s": sr.report.latency_s,
        "cost_usd": sr.report.cost_usd,
        "hallucination_warning": sr.grounding_score < 0.8,
    }
