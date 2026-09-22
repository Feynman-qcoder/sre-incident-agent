"""DataSource Protocol — the central abstraction seam.

Every component (agent tools, eval harness, scripts) receives a DataSource.
LiveDataSource makes HTTP calls to a running cluster.
ReplayDataSource reads from a snapshot directory on disk.
Neither the agent nor the harness imports HTTP libraries directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DataSource(Protocol):
    """Read-only access to telemetry backends for a given incident window."""

    def query_prometheus_instant(
        self,
        query: str,
        time: str,
    ) -> dict[str, object]:
        """Execute a PromQL instant query.

        Returns raw Prometheus API result dict:
        {"metric": {...labels}, "value": [timestamp, "value_str"]}
        or empty dict if no result.
        """
        ...

    def query_prometheus_range(
        self,
        query: str,
        start: str,
        end: str,
        step: str = "30s",
    ) -> list[dict[str, object]]:
        """Execute a PromQL range query.

        Returns list of {"metric": {...labels}, "values": [[ts, val_str], ...]}
        Each element is one time series.
        """
        ...

    def search_traces(
        self,
        service_name: str,
        start: str,
        end: str,
        min_duration_ms: int | None = None,
        error_only: bool = False,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """Search Tempo for traces matching criteria.

        Returns list of trace summaries:
        {"traceID": str, "rootServiceName": str, "rootTraceName": str,
         "startTimeUnixNano": str, "durationMs": int, "spanSets": [...]}
        """
        ...

    def get_trace(self, trace_id: str) -> dict[str, object]:
        """Fetch a full trace (span tree) from Tempo by ID."""
        ...

    def query_loki(
        self,
        logql: str,
        start: str,
        end: str,
        limit: int = 100,
        direction: str = "backward",
    ) -> list[dict[str, object]]:
        """Execute a LogQL query.

        Returns list of stream results:
        {"stream": {...labels}, "values": [[ts_nanosec_str, line_str], ...]}
        """
        ...

    def get_pod_events(
        self,
        namespace: str,
        pod_name_prefix: str | None = None,
        since_seconds: int = 600,
    ) -> list[dict[str, object]]:
        """Fetch Kubernetes events for pods in a namespace.

        Returns list of event dicts with keys:
        type, reason, message, count, first_time, last_time, involved_object_name
        """
        ...

    def get_service_topology(self, namespace: str) -> dict[str, list[str]]:
        """Return service dependency graph.

        Returns {service_name: [downstream_service_names]}
        Inferred from static config or OTel span data.
        """
        ...
