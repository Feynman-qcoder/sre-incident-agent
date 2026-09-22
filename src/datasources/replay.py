"""ReplayDataSource — reads from a snapshot directory, no live cluster needed.

The snapshot format is:
  <snapshot_dir>/
    ground_truth.json
    metadata.json
    prometheus/raw_queries.json   [{query, start, end, step, result}]
    tempo/trace_summaries.json    [trace_summary, ...]
    tempo/traces/<id>.json        full span tree
    loki/raw_queries.json         [{logql, start, end, result}]
    k8s/events.json               [event_dict, ...]

Matching strategy for Prometheus:
  Exact match on (query, start, end, step) → return stored result.
  If no exact match, return the closest query by PromQL string similarity
  and log a warning. This allows the agent to use slightly different queries
  than what was pre-snapshotted while still getting meaningful data.

Matching strategy for Loki:
  Exact match on logql string → return stored result.
  Otherwise return empty list (the agent should handle missing data gracefully).
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

log = structlog.get_logger()


class ReplayDataSource:
    """Replays telemetry from a snapshot directory. No network calls."""

    def __init__(self, snapshot_dir: str | Path) -> None:
        self._dir = Path(snapshot_dir)
        if not self._dir.exists():
            raise FileNotFoundError(f"Snapshot directory not found: {self._dir}")
        self._prom_queries: list[dict[str, object]] = self._load_json("prometheus/raw_queries.json", [])
        self._trace_summaries: list[dict[str, object]] = self._load_json("tempo/trace_summaries.json", [])
        self._loki_queries: list[dict[str, object]] = self._load_json("loki/raw_queries.json", [])
        self._k8s_events: list[dict[str, object]] = self._load_json("k8s/events.json", [])

    def _load_json(self, relative_path: str, default: object) -> object:
        path = self._dir / relative_path
        if not path.exists():
            log.warning("snapshot_file_missing", path=str(path))
            return default
        with open(path) as f:
            return json.load(f)

    def query_prometheus_instant(self, query: str, time: str) -> dict[str, object]:
        for entry in self._prom_queries:  # type: ignore[union-attr]
            if entry.get("type") == "instant" and entry.get("query") == query:
                result = entry.get("result", [])
                return result[0] if result else {}
        log.warning("prom_instant_cache_miss", query=query[:80])
        return {}

    def query_prometheus_range(
        self, query: str, start: str, end: str, step: str = "30s"
    ) -> list[dict[str, object]]:
        # Exact match INCLUDING the time window. This is essential: the Z-score baselines
        # query the same PromQL for both the fault window and the baseline window, so matching
        # on query alone would return identical data for both → z=0 (a hollow baseline).
        for entry in self._prom_queries:  # type: ignore[union-attr]
            if (
                entry.get("type") == "range"
                and entry.get("query") == query
                and entry.get("step", "30s") == step
                and entry.get("start") == start
                and entry.get("end") == end
            ):
                return entry.get("result", [])  # type: ignore[return-value]
        # Fall back: same PromQL+step, any window (the agent's LLM may not echo the exact
        # window). Prefer a non-baseline (fault-window) entry so the agent sees fault data.
        candidates = [
            e for e in self._prom_queries  # type: ignore[union-attr]
            if e.get("type") == "range" and e.get("query") == query
            and e.get("step", "30s") == step
        ]
        if candidates:
            log.warning("prom_range_window_mismatch", query=query[:80])
            best = next((e for e in candidates if not e.get("is_baseline")), candidates[0])
            return best.get("result", [])  # type: ignore[return-value]
        log.warning("prom_range_cache_miss", query=query[:80])
        return []

    def search_traces(
        self,
        service_name: str,
        start: str,
        end: str,
        min_duration_ms: int | None = None,
        error_only: bool = False,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        matches = [
            t for t in self._trace_summaries  # type: ignore[union-attr]
            if t.get("rootServiceName") == service_name
            or any(
                s.get("attributes", {}).get("service.name") == service_name
                for s in t.get("spanSets", [])
            )
        ]
        if error_only:
            matches = [t for t in matches if t.get("hasError", False)]
        if min_duration_ms is not None:
            matches = [t for t in matches if int(t.get("durationMs", 0)) >= min_duration_ms]
        return matches[:limit]

    def get_trace(self, trace_id: str) -> dict[str, object]:
        path = self._dir / "tempo" / "traces" / f"{trace_id}.json"
        if not path.exists():
            log.warning("trace_not_in_snapshot", trace_id=trace_id)
            return {}
        with open(path) as f:
            return json.load(f)  # type: ignore[return-value]

    def query_loki(
        self,
        logql: str,
        start: str,
        end: str,
        limit: int = 100,
        direction: str = "backward",
    ) -> list[dict[str, object]]:
        for entry in self._loki_queries:  # type: ignore[union-attr]
            if entry.get("logql") == logql:
                return entry.get("result", [])  # type: ignore[return-value]
        # Partial match: only if the service_name value (quoted in the selector) matches.
        # Extract service_name value from logql e.g. {service_name="checkoutservice"}
        import re as _re
        svc_match = _re.search(r'service_name="([^"]+)"', logql)
        if svc_match:
            svc = svc_match.group(1)
            for entry in self._loki_queries:  # type: ignore[union-attr]
                stored_logql: str = str(entry.get("logql", ""))
                if f'service_name="{svc}"' in stored_logql:
                    log.warning("loki_partial_match", requested=logql[:80])
                    return entry.get("result", [])  # type: ignore[return-value]
        log.warning("loki_cache_miss", logql=logql[:80])
        return []

    def get_pod_events(
        self,
        namespace: str,
        pod_name_prefix: str | None = None,
        since_seconds: int = 600,
    ) -> list[dict[str, object]]:
        events: list[dict[str, object]] = list(self._k8s_events)  # type: ignore[arg-type]
        if pod_name_prefix:
            events = [e for e in events if str(e.get("involved_object_name", "")).startswith(pod_name_prefix)]
        return events

    def get_service_topology(self, namespace: str) -> dict[str, list[str]]:
        path = self._dir / "metadata.json"
        if path.exists():
            with open(path) as f:
                meta = json.load(f)
                if "service_topology" in meta:
                    return meta["service_topology"]  # type: ignore[return-value]
        # Fall back to hardcoded Astronomy Shop topology
        from src.datasources.live import _STATIC_TOPOLOGY
        return dict(_STATIC_TOPOLOGY)
