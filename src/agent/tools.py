"""Agent tool functions — thin wrappers around DataSource with Layer 1+2 compression.

These functions are bound to the LLM via LangChain's bind_tools().
They never import HTTP libraries directly — all I/O goes through a DataSource.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import structlog

from src.agent.context_manager import (
    ContextBudget,
    compress_loki,
    compress_prometheus_range,
    compress_traces,
)

if TYPE_CHECKING:
    from src.datasources.protocol import DataSource

log = structlog.get_logger()

MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "8"))


def make_tools(ds: DataSource, budget: ContextBudget) -> list:  # type: ignore[type-arg]
    """Return LangChain tool functions bound to a specific DataSource and budget."""
    from langchain_core.tools import tool

    @tool
    def query_prometheus_range(
        query: str,
        start: str,
        end: str,
        step: str = "30s",
    ) -> str:
        """Execute a PromQL range query against Prometheus.

        Returns a compressed statistical summary (mean, p50, p95, p99, max, anomaly window).
        Use this to detect anomalies in metrics like error_rate, p99_latency, cpu_usage.

        Args:
            query: PromQL expression. Use service_name label to filter by service.
            start: ISO-8601 UTC start time.
            end: ISO-8601 UTC end time.
            step: Resolution step (default: 30s). Use 30s for incident windows.
        """
        try:
            results = ds.query_prometheus_range(query, start, end, step)
            compressed = compress_prometheus_range(results, query)
            return budget.consume(compressed)
        except Exception as e:
            log.warning("tool_error", tool="query_prometheus_range", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def query_prometheus_instant(query: str, time: str) -> str:
        """Execute a PromQL instant query for a single point in time.

        Args:
            query: PromQL expression.
            time: ISO-8601 UTC timestamp.
        """
        try:
            result = ds.query_prometheus_instant(query, time)
            if not result:
                return "[no data]"
            return budget.consume(str(result)[:500])
        except Exception as e:
            log.warning("tool_error", tool="query_prometheus_instant", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def search_traces(
        service_name: str,
        start: str,
        end: str,
        min_duration_ms: int = 0,
        error_only: bool = False,
        limit: int = 20,
    ) -> str:
        """Search Tempo for distributed traces matching criteria.

        Returns a summary: total count, error count, p95 duration, and top-3 trace IDs.
        Use error_only=True when investigating error rate anomalies.
        Use min_duration_ms when investigating latency anomalies.

        Args:
            service_name: Exact service name (e.g. 'checkoutservice').
            start: ISO-8601 UTC start.
            end: ISO-8601 UTC end.
            min_duration_ms: Only include traces longer than this (0 = all).
            error_only: Only include traces with errors.
            limit: Max traces to fetch (default 20).
        """
        try:
            traces = ds.search_traces(
                service_name, start, end,
                min_duration_ms=min_duration_ms if min_duration_ms > 0 else None,
                error_only=error_only,
                limit=limit,
            )
            compressed = compress_traces(traces)
            return budget.consume(compressed)
        except Exception as e:
            log.warning("tool_error", tool="search_traces", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def get_trace(trace_id: str) -> str:
        """Fetch a full trace by ID to inspect individual span errors and timings.

        Use this on a specific trace_id you found from search_traces.

        Args:
            trace_id: Exact trace ID returned by search_traces.
        """
        try:
            trace = ds.get_trace(trace_id)
            if not trace:
                return f"[trace {trace_id} not found]"
            # Return first 1000 chars of JSON — enough to see root spans
            return budget.consume(str(trace)[:1000])
        except Exception as e:
            log.warning("tool_error", tool="get_trace", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def query_loki(
        logql: str,
        start: str,
        end: str,
        limit: int = 100,
    ) -> str:
        """Execute a LogQL query against Loki to retrieve logs.

        Returns deduplicated error patterns and log level counts.
        Use label selectors like {service_name="checkoutservice"} and filter with |= "error".

        Args:
            logql: LogQL query string.
            start: ISO-8601 UTC start.
            end: ISO-8601 UTC end.
            limit: Max log lines (default 100).
        """
        try:
            results = ds.query_loki(logql, start, end, limit=limit)
            compressed = compress_loki(results)
            return budget.consume(compressed)
        except Exception as e:
            log.warning("tool_error", tool="query_loki", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def get_pod_events(
        namespace: str,
        pod_name_prefix: str = "",
        since_seconds: int = 600,
    ) -> str:
        """Fetch Kubernetes pod events (OOMKilled, BackOff, FailedMount, etc.).

        Useful to detect pod crash loops and resource pressure.

        Args:
            namespace: Kubernetes namespace (e.g. 'otel-demo').
            pod_name_prefix: Filter to pods starting with this string.
            since_seconds: Look back this many seconds (default 600 = 10 min).
        """
        try:
            events = ds.get_pod_events(namespace, pod_name_prefix or None, since_seconds)
            if not events:
                return "[no K8s events found]"
            lines = [f"  {e['reason']}: {e['message'][:120]} (count={e['count']})" for e in events[:10]]
            return budget.consume("K8s events:\n" + "\n".join(lines))
        except Exception as e:
            log.warning("tool_error", tool="get_pod_events", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def get_service_topology(namespace: str) -> str:
        """Return the service dependency graph for the given namespace.

        Use this first to understand which services call which, so you can
        identify upstream vs downstream failure propagation.

        Args:
            namespace: Kubernetes namespace.
        """
        try:
            topo = ds.get_service_topology(namespace)
            lines = [f"  {svc} → {', '.join(deps) or '(leaf)'}" for svc, deps in sorted(topo.items())]
            return budget.consume("Service topology:\n" + "\n".join(lines))
        except Exception as e:
            log.warning("tool_error", tool="get_service_topology", error=str(e))
            return f"[ERROR: {e}]"

    return [
        query_prometheus_range,
        query_prometheus_instant,
        search_traces,
        get_trace,
        query_loki,
        get_pod_events,
        get_service_topology,
    ]
