"""LiveDataSource — makes HTTP calls to a running cluster's NodePort backends."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx
import structlog
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

log = structlog.get_logger()

# OTel Astronomy Shop 2.x service names. These match `service.name` (set from the pod label
# app.kubernetes.io/component) and the pod-name prefix `<svc>-<hash>`. The 1.x names
# (checkoutservice, cartservice, …) are GONE — the demo renamed every service in 2.0.
ASTRONOMY_SHOP_SERVICES = [
    "frontend", "cart", "checkout", "currency",
    "email", "payment", "product-catalog",
    "recommendation", "shipping", "ad",
    "load-generator", "accounting", "fraud-detection",
    "quote", "flagd",
]

# Static dependency graph for OTel Astronomy Shop (frontend → downstream calls)
_STATIC_TOPOLOGY: dict[str, list[str]] = {
    "frontend": ["checkout", "recommendation", "product-catalog",
                 "cart", "shipping", "currency", "ad"],
    "checkout": ["cart", "payment", "email",
                 "shipping", "currency", "product-catalog"],
    "cart": [],
    "payment": [],
    "email": [],
    "shipping": ["quote"],
    "quote": [],
    "product-catalog": [],
    "recommendation": ["product-catalog"],
    "currency": [],
    "ad": [],
    "load-generator": ["frontend"],
    "accounting": ["checkout"],
    "fraud-detection": ["checkout"],
    "flagd": [],
}


class LiveDataSource:
    """Queries live cluster backends directly via HTTP."""

    def __init__(
        self,
        prometheus_url: str | None = None,
        tempo_url: str | None = None,
        loki_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._prom = (prometheus_url or os.getenv("PROMETHEUS_URL", "http://localhost:9090")).rstrip("/")
        self._tempo = (tempo_url or os.getenv("TEMPO_URL", "http://localhost:3200")).rstrip("/")
        self._loki = (loki_url or os.getenv("LOKI_URL", "http://localhost:3100")).rstrip("/")
        self._client = httpx.Client(timeout=timeout)
        self._k8s: k8s_client.CoreV1Api | None = None

    def _k8s_client(self) -> k8s_client.CoreV1Api:
        if self._k8s is None:
            kube_context = os.getenv("KUBE_CONTEXT", "kind-sre-incident-agent")
            try:
                k8s_config.load_kube_config(context=kube_context)
            except Exception:
                k8s_config.load_incluster_config()
            self._k8s = k8s_client.CoreV1Api()
        return self._k8s

    def query_prometheus_instant(self, query: str, time: str) -> dict[str, object]:
        resp = self._client.get(
            f"{self._prom}/api/v1/query",
            params={"query": query, "time": time},
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("data", {}).get("result", [])
        return results[0] if results else {}

    def query_prometheus_range(
        self, query: str, start: str, end: str, step: str = "30s"
    ) -> list[dict[str, object]]:
        resp = self._client.get(
            f"{self._prom}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("result", [])

    def search_traces(
        self,
        service_name: str,
        start: str,
        end: str,
        min_duration_ms: int | None = None,
        error_only: bool = False,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        params: dict[str, object] = {
            "service.name": service_name,
            "start": _to_unix_s(start),
            "end": _to_unix_s(end),
            "limit": limit,
        }
        if min_duration_ms is not None:
            params["minDuration"] = f"{min_duration_ms}ms"
        if error_only:
            params["tags"] = "error=true"
        resp = self._client.get(f"{self._tempo}/api/search", params=params)
        resp.raise_for_status()
        return resp.json().get("traces", [])

    def get_trace(self, trace_id: str) -> dict[str, object]:
        resp = self._client.get(f"{self._tempo}/api/traces/{trace_id}")
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]

    def query_loki(
        self,
        logql: str,
        start: str,
        end: str,
        limit: int = 100,
        direction: str = "backward",
    ) -> list[dict[str, object]]:
        params = {
            "query": logql,
            "start": _to_unix_ns(start),
            "end": _to_unix_ns(end),
            "limit": limit,
            "direction": direction,
        }
        resp = self._client.get(f"{self._loki}/loki/api/v1/query_range", params=params)
        resp.raise_for_status()
        return resp.json().get("data", {}).get("result", [])

    def get_pod_events(
        self,
        namespace: str,
        pod_name_prefix: str | None = None,
        since_seconds: int = 600,
    ) -> list[dict[str, object]]:
        api = self._k8s_client()
        events = api.list_namespaced_event(namespace=namespace)
        cutoff = datetime.now(UTC).timestamp() - since_seconds
        results: list[dict[str, object]] = []
        for ev in events.items:
            if ev.last_timestamp and ev.last_timestamp.timestamp() < cutoff:
                continue
            name: str = ev.involved_object.name or ""
            if pod_name_prefix and not name.startswith(pod_name_prefix):
                continue
            results.append({
                "type": ev.type,
                "reason": ev.reason,
                "message": ev.message,
                "count": ev.count,
                "first_time": str(ev.first_timestamp),
                "last_time": str(ev.last_timestamp),
                "involved_object_name": name,
            })
        return results

    def get_service_topology(self, namespace: str) -> dict[str, list[str]]:
        return dict(_STATIC_TOPOLOGY)

    def close(self) -> None:
        self._client.close()


def _to_unix_ns(ts: str) -> str:
    """Convert ISO-8601 to nanosecond Unix timestamp (Loki format)."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return str(int(dt.timestamp() * 1e9))
    except ValueError:
        return ts


def _to_unix_s(ts: str) -> int:
    """Convert ISO-8601 to second Unix timestamp (Tempo search format)."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except ValueError:
        return 0
