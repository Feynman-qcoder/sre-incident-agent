"""Tests for DataSource abstraction (ReplayDataSource against fixture snapshot)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.datasources.protocol import DataSource
from src.datasources.replay import ReplayDataSource
from src.telemetry_queries import LOKI_QUERIES, METRIC_QUERIES


class TestReplayDataSourceProtocol:
    """Verify ReplayDataSource satisfies the DataSource Protocol."""

    def test_is_datasource_instance(self, replay_ds: ReplayDataSource) -> None:
        assert isinstance(replay_ds, DataSource)


class TestReplayPrometheus:
    def test_range_query_exact_match(self, replay_ds: ReplayDataSource) -> None:
        query = METRIC_QUERIES["error_rate"].format(svc="checkout")
        result = replay_ds.query_prometheus_range(
            query,
            start="2024-01-15T13:59:00+00:00",
            end="2024-01-15T14:06:00+00:00",
        )
        assert len(result) == 1
        values = result[0]["values"]
        assert len(values) > 0
        # The fault window should show a high error rate for the crashed service.
        fault_values = [float(v[1]) for v in values]
        assert max(fault_values) >= 0.9

    def test_range_query_distinguishes_fault_and_baseline_windows(
        self, replay_ds: ReplayDataSource
    ) -> None:
        # Same PromQL, different windows must return different data (else Z-scores are hollow).
        query = METRIC_QUERIES["error_rate"].format(svc="checkout")
        fault = replay_ds.query_prometheus_range(
            query, "2024-01-15T13:59:00+00:00", "2024-01-15T14:06:00+00:00"
        )
        baseline = replay_ds.query_prometheus_range(
            query, "2024-01-15T13:29:00+00:00", "2024-01-15T13:59:00+00:00"
        )
        assert float(fault[0]["values"][0][1]) >= 0.9
        assert float(baseline[0]["values"][0][1]) == 0.0

    def test_range_query_cache_miss_returns_empty(self, replay_ds: ReplayDataSource) -> None:
        result = replay_ds.query_prometheus_range(
            "nonexistent_metric_query_xyz{service=\"nope\"}",
            start="2024-01-15T13:59:00+00:00",
            end="2024-01-15T14:06:00+00:00",
        )
        assert result == []

    def test_instant_query_miss_returns_empty_dict(self, replay_ds: ReplayDataSource) -> None:
        result = replay_ds.query_prometheus_instant(
            "up{job='nonexistent'}",
            time="2024-01-15T14:00:00+00:00",
        )
        assert result == {}


class TestReplayTempo:
    def test_search_traces_returns_summaries(self, replay_ds: ReplayDataSource) -> None:
        traces = replay_ds.search_traces(
            "checkout",
            start="2024-01-15T13:59:00+00:00",
            end="2024-01-15T14:06:00+00:00",
        )
        assert len(traces) > 0
        assert all("traceID" in t for t in traces)

    def test_search_traces_error_only_filter(self, replay_ds: ReplayDataSource) -> None:
        all_traces = replay_ds.search_traces(
            "checkout",
            start="2024-01-15T13:59:00+00:00",
            end="2024-01-15T14:06:00+00:00",
            error_only=False,
        )
        error_traces = replay_ds.search_traces(
            "checkout",
            start="2024-01-15T13:59:00+00:00",
            end="2024-01-15T14:06:00+00:00",
            error_only=True,
        )
        assert len(error_traces) <= len(all_traces)
        assert all(t.get("hasError") for t in error_traces)

    def test_search_traces_limit(self, replay_ds: ReplayDataSource) -> None:
        traces = replay_ds.search_traces(
            "frontend",
            start="2024-01-15T13:59:00+00:00",
            end="2024-01-15T14:06:00+00:00",
            limit=1,
        )
        assert len(traces) <= 1

    def test_get_trace_not_in_snapshot_returns_empty(self, replay_ds: ReplayDataSource) -> None:
        result = replay_ds.get_trace("nonexistent-trace-id-xyz")
        assert result == {}


class TestReplayLoki:
    def test_query_loki_exact_match(self, replay_ds: ReplayDataSource) -> None:
        result = replay_ds.query_loki(
            LOKI_QUERIES["error_logs"].format(svc="checkout"),
            start="2024-01-15T13:59:00+00:00",
            end="2024-01-15T14:06:00+00:00",
        )
        assert len(result) > 0
        assert "values" in result[0]
        assert len(result[0]["values"]) == 3

    def test_query_loki_miss_returns_empty(self, replay_ds: ReplayDataSource) -> None:
        result = replay_ds.query_loki(
            '{service_name="nonexistent_service_xyz"} |= "error"',
            start="2024-01-15T13:59:00+00:00",
            end="2024-01-15T14:06:00+00:00",
        )
        assert result == []


class TestReplayK8s:
    def test_get_pod_events_returns_list(self, replay_ds: ReplayDataSource) -> None:
        events = replay_ds.get_pod_events("otel-demo")
        assert isinstance(events, list)
        assert len(events) > 0

    def test_get_pod_events_prefix_filter(self, replay_ds: ReplayDataSource) -> None:
        all_events = replay_ds.get_pod_events("otel-demo")
        filtered = replay_ds.get_pod_events("otel-demo", pod_name_prefix="checkout")
        assert len(filtered) <= len(all_events)
        assert all(e["involved_object_name"].startswith("checkout") for e in filtered)

    def test_get_pod_events_no_match_prefix(self, replay_ds: ReplayDataSource) -> None:
        events = replay_ds.get_pod_events("otel-demo", pod_name_prefix="nonexistent")
        assert events == []


class TestReplayTopology:
    def test_get_service_topology_returns_dict(self, replay_ds: ReplayDataSource) -> None:
        topo = replay_ds.get_service_topology("otel-demo")
        assert isinstance(topo, dict)
        assert "checkout" in topo
        assert "frontend" in topo

    def test_frontend_has_downstream_services(self, replay_ds: ReplayDataSource) -> None:
        topo = replay_ds.get_service_topology("otel-demo")
        assert "checkout" in topo["frontend"]


class TestReplayInitErrors:
    def test_nonexistent_dir_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            ReplayDataSource("/nonexistent/path/that/does/not/exist")

    def test_missing_files_handled_gracefully(self, tmp_path: Path) -> None:
        """A snapshot dir with only ground_truth.json should not crash."""
        (tmp_path / "ground_truth.json").write_text('{"scenario_id": "test"}')
        ds = ReplayDataSource(tmp_path)
        assert ds.query_prometheus_range("up", "2024-01-15T14:00:00Z", "2024-01-15T14:05:00Z") == []
        assert ds.search_traces("svc", "2024-01-15T14:00:00Z", "2024-01-15T14:05:00Z") == []
        assert ds.query_loki('{job="test"}', "2024-01-15T14:00:00Z", "2024-01-15T14:05:00Z") == []
        assert ds.get_pod_events("otel-demo") == []
