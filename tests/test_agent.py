"""Tests for agent components using ReplayDataSource (no LLM calls)."""

from __future__ import annotations

import pytest

from src.agent.context_manager import (
    ContextBudget,
    compress_loki,
    compress_prometheus_range,
    compress_traces,
)
from src.agent.schemas import (
    EvidenceItem,
    InvestigationReport,
    RootCauseHypothesis,
    initial_state,
)
from src.datasources.replay import ReplayDataSource
from src.telemetry_queries import LOKI_QUERIES, METRIC_QUERIES

# ── Schema tests ───────────────────────────────────────────────────────────────

class TestInvestigationReportSchema:
    def test_valid_minimal_report(self) -> None:
        report = InvestigationReport(
            incident_id="test-001",
            investigation_start_ts="2024-01-15T14:00:00Z",
            investigation_end_ts="2024-01-15T14:02:00Z",
            root_causes=[
                RootCauseHypothesis(
                    rank=1,
                    service="checkoutservice",
                    fault_type="pod_crash",
                    description="Pod crash loop detected",
                    confidence=0.9,
                    evidence=[],
                )
            ],
            fault_type_classification="pod_crash",
        )
        assert report.root_causes[0].service == "checkoutservice"
        assert report.fault_type_classification == "pod_crash"
        assert report.grounding_score == 0.0  # default

    def test_evidence_item_requires_query_or_id(self) -> None:
        ev = EvidenceItem(
            signal_type="metric",
            query_or_id='sum(rate(http_server_request_duration_seconds_count{service_name="checkoutservice"}[2m]))',
            observed_value="error_rate=0.95",
        )
        assert ev.signal_type == "metric"
        assert "checkoutservice" in ev.query_or_id

    def test_report_rejects_too_many_root_causes(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            InvestigationReport(
                incident_id="test",
                investigation_start_ts="2024-01-15T14:00:00Z",
                investigation_end_ts="2024-01-15T14:02:00Z",
                root_causes=[
                    RootCauseHypothesis(rank=i+1, service="svc", fault_type="pod_crash",
                                        description="x", confidence=0.5)
                    for i in range(5)  # max is 3
                ],
                fault_type_classification="pod_crash",
            )

    def test_confidence_bounds(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RootCauseHypothesis(
                rank=1, service="svc", fault_type="pod_crash",
                description="x", confidence=1.5,  # > 1.0
            )

    def test_initial_state_structure(self) -> None:
        state = initial_state(
            incident_id="inc-001",
            incident_start_ts="2024-01-15T14:00:00Z",
            incident_end_ts="2024-01-15T14:10:00Z",
        )
        assert state["incident_id"] == "inc-001"
        assert state["messages"] == []
        assert state["tool_calls_log"] == []
        assert state["iteration_count"] == 0
        assert state["final_report"] is None


# ── Context manager tests ──────────────────────────────────────────────────────

class TestContextBudget:
    def test_budget_consumes_short_text(self) -> None:
        budget = ContextBudget(budget=10000)
        text = "hello world"
        result = budget.consume(text)
        assert result == text
        assert budget.used_tokens > 0

    def test_budget_truncates_on_overflow(self) -> None:
        budget = ContextBudget(budget=100)
        long_text = "x" * 10000
        result = budget.consume(long_text)
        assert "TRUNCATED" in result
        assert len(result) < len(long_text)

    def test_budget_remaining_decreases(self) -> None:
        budget = ContextBudget(budget=1000)
        initial = budget.remaining()
        budget.consume("a" * 200)
        assert budget.remaining() < initial


class TestCompressPrometheus:
    def test_compress_empty(self) -> None:
        result = compress_prometheus_range([], "up")
        assert "no data" in result

    def test_compress_returns_stats(self) -> None:
        raw = [{"metric": {}, "values": [[1.0, "0.10"], [2.0, "0.20"], [3.0, "0.15"]]}]
        result = compress_prometheus_range(raw, "error_rate_query")
        assert "mean=" in result
        assert "p99=" in result
        assert "max=" in result

    def test_compress_detects_anomaly(self) -> None:
        # A late spike well above 3x the mean must be flagged as an anomaly window.
        raw = [{"metric": {}, "values": [
            [1.0, "0.01"], [2.0, "0.01"], [3.0, "0.01"], [4.0, "0.90"]]}]
        result = compress_prometheus_range(raw, "error_rate_query")
        assert "anomaly" in result


class TestCompressTraces:
    def test_compress_empty(self) -> None:
        result = compress_traces([])
        assert "no traces" in result

    def test_compress_returns_counts(self, replay_ds: ReplayDataSource) -> None:
        traces = replay_ds.search_traces(
            "checkout",
            start="2024-01-15T13:59:00+00:00",
            end="2024-01-15T14:06:00+00:00",
        )
        result = compress_traces(traces)
        assert "total" in result
        assert "errors" in result or "error" in result


class TestCompressLoki:
    def test_compress_empty(self) -> None:
        result = compress_loki([])
        assert "no logs" in result

    def test_compress_counts_levels(self, replay_ds: ReplayDataSource) -> None:
        logs = replay_ds.query_loki(
            LOKI_QUERIES["error_logs"].format(svc="checkout"),
            start="2024-01-15T13:59:00+00:00",
            end="2024-01-15T14:06:00+00:00",
        )
        result = compress_loki(logs)
        assert "error=" in result or "error" in result.lower()


# ── Tools integration tests (no LLM, only tool wrappers) ──────────────────────

class TestToolWrappers:
    def test_tools_are_created(self, replay_ds: ReplayDataSource) -> None:
        budget = ContextBudget()
        from src.agent.tools import make_tools
        tools = make_tools(replay_ds, budget)
        tool_names = {t.name for t in tools}
        assert "query_prometheus_range" in tool_names
        assert "search_traces" in tool_names
        assert "query_loki" in tool_names
        assert "get_pod_events" in tool_names
        assert "get_service_topology" in tool_names

    def test_query_prometheus_range_tool(self, replay_ds: ReplayDataSource) -> None:
        budget = ContextBudget()
        from src.agent.tools import make_tools
        tools = {t.name: t for t in make_tools(replay_ds, budget)}
        result = tools["query_prometheus_range"].invoke({
            "query": METRIC_QUERIES["error_rate"].format(svc="checkout"),
            "start": "2024-01-15T13:59:00+00:00",
            "end": "2024-01-15T14:06:00+00:00",
        })
        assert isinstance(result, str)
        assert len(result) > 0
        assert "ERROR" not in result

    def test_search_traces_tool(self, replay_ds: ReplayDataSource) -> None:
        budget = ContextBudget()
        from src.agent.tools import make_tools
        tools = {t.name: t for t in make_tools(replay_ds, budget)}
        result = tools["search_traces"].invoke({
            "service_name": "checkout",
            "start": "2024-01-15T13:59:00+00:00",
            "end": "2024-01-15T14:06:00+00:00",
            "error_only": True,
        })
        assert isinstance(result, str)
        assert "[ERROR:" not in result  # "[ERROR:" is tool failure; "ERROR" is status label

    def test_get_service_topology_tool(self, replay_ds: ReplayDataSource) -> None:
        budget = ContextBudget()
        from src.agent.tools import make_tools
        tools = {t.name: t for t in make_tools(replay_ds, budget)}
        result = tools["get_service_topology"].invoke({"namespace": "otel-demo"})
        assert "checkout" in result
        assert "frontend" in result
