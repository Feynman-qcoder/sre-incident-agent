"""Central data models for the SRE-Copilot agent.

All other agent modules and the eval harness import from here.
Changing a field here is a breaking change — update tests and eval harness accordingly.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

# ── Output schema ──────────────────────────────────────────────────────────────

class EvidenceItem(BaseModel):
    """A single grounded piece of evidence supporting a hypothesis.

    query_or_id MUST correspond to an actual tool call made during the investigation.
    The grounding verifier cross-checks this against tool_calls_log.
    """

    signal_type: Literal["metric", "trace", "log", "k8s_event"]
    query_or_id: str = Field(
        description="Exact PromQL, LogQL, trace_id, or K8s event UID used to obtain this evidence"
    )
    observed_value: str = Field(
        description="Human-readable observed value, e.g. 'error_rate=0.94 at 14:03:22'"
    )
    expected_baseline: str | None = Field(
        default=None,
        description="Expected normal value, e.g. 'error_rate < 0.01 (p99 last 24h)'"
    )


class RootCauseHypothesis(BaseModel):
    rank: int = Field(ge=1, le=10, description="1 = most likely")
    service: str = Field(description="Exact service name from OTel Astronomy Shop")
    fault_type: Literal[
        "pod_crash",
        "high_latency",
        "cpu_stress",
        "memory_stress",
        "http_abort",
        "dependency_failure",
        "unknown",
    ]
    description: str = Field(description="1-2 sentence explanation of the hypothesis")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class InvestigationReport(BaseModel):
    incident_id: str
    investigation_start_ts: str
    investigation_end_ts: str
    root_causes: list[RootCauseHypothesis] = Field(
        description="Top-3 hypotheses ordered by rank (rank 1 = most likely)",
        min_length=1,
        max_length=3,
    )
    remediation_steps: list[str] = Field(
        description="Ordered list of remediation actions",
        default_factory=list,
    )
    fault_type_classification: str = Field(
        description="Top-1 fault type (= root_causes[0].fault_type)"
    )
    # grounding_score is injected by the harness after verification, not self-reported
    grounding_score: float = Field(default=0.0, ge=0.0, le=1.0)
    latency_s: float = Field(default=0.0)
    cost_usd: float = Field(default=0.0)
    total_prompt_tokens: int = Field(default=0)
    total_completion_tokens: int = Field(default=0)
    llm_model: str = Field(default="")
    agent_version: str = Field(default="0.1.0")


# ── LangGraph state ────────────────────────────────────────────────────────────

class AgentState(dict):  # type: ignore[type-arg]
    """LangGraph state for the investigation graph.

    Uses TypedDict-style annotation via __annotations__ for LangGraph compatibility.
    messages uses operator.add reducer to accumulate across nodes.
    """

    # Incident context (set at entry, immutable during graph)
    incident_id: str
    incident_start_ts: str    # ISO-8601 UTC
    incident_end_ts: str      # ISO-8601 UTC
    affected_namespace: str

    # Accumulated during execution
    messages: Annotated[list[BaseMessage], operator.add]
    tool_calls_log: list[dict[str, object]]   # each tool invocation + response
    metrics_context: str        # compressed Prometheus summaries
    traces_context: str         # compressed trace summaries
    logs_context: str           # compressed log summaries
    hypotheses: list[dict[str, object]]       # [{service, fault_type, score, evidence}]
    iteration_count: int        # guard against infinite tool-call loops
    final_report: InvestigationReport | None


def initial_state(
    incident_id: str,
    incident_start_ts: str,
    incident_end_ts: str,
    affected_namespace: str = "otel-demo",
    memory_hint: str = "",
) -> dict[str, object]:
    """Return a fresh AgentState dict for graph.invoke().

    ``memory_hint``（add-incident-memory D5）：非空时 graph 在首轮插入独立
    Hint 消息（历史调查参考，与证据链隔离）；空 = 行为与变更前一致。
    """
    return {
        "incident_id": incident_id,
        "incident_start_ts": incident_start_ts,
        "incident_end_ts": incident_end_ts,
        "affected_namespace": affected_namespace,
        "memory_hint": memory_hint,
        "messages": [],
        "tool_calls_log": [],
        "metrics_context": "",
        "traces_context": "",
        "logs_context": "",
        "hypotheses": [],
        "iteration_count": 0,
        "final_report": None,
    }
