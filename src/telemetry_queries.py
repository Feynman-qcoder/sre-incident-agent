"""Canonical telemetry query templates — single source of truth.

The snapshot script captures *exactly* these queries; the baselines and (via the system
prompt) the agent replay them. ReplayDataSource matches on the query string, so every
consumer MUST format from these identical templates or replay returns empty.

`{svc}` is an OTel Astronomy Shop 2.x service name (e.g. "checkout"), which matches:
  - the spanmetrics `service_name` label (RED metrics from the spanmetrics connector),
  - the pod-name prefix `<svc>-<hash>` (cAdvisor / kube-state metrics),
  - the Tempo `service.name` resource attribute.

Design notes:
  - error_rate / request_rate / p99 come from the spanmetrics connector (`calls_total`,
    `duration_milliseconds_*`). This is language-agnostic: every service emits the same
    metric regardless of being Go/gRPC, Node/HTTP, etc. We restrict to SERVER spans
    (inbound requests handled by the service).
  - `... or vector(0)` makes error/request rate return 0 (not empty) when a service has no
    matching spans, so Z-score baselines see a real zero baseline and a signal appearing
    from nothing reads as an anomaly.
  - cpu / memory / restarts are pod-labelled (reliable identity regardless of service.name).
"""

from __future__ import annotations

NAMESPACE = "otel-demo"

# signal_name -> PromQL template (parametrised by {svc})
METRIC_QUERIES: dict[str, str] = {
    "error_rate": (
        'sum(rate(calls_total{{service_name="{svc}",span_kind="SPAN_KIND_SERVER",'
        'status_code="STATUS_CODE_ERROR"}}[2m])) or vector(0)'
    ),
    "request_rate": (
        'sum(rate(calls_total{{service_name="{svc}",span_kind="SPAN_KIND_SERVER"}}[2m]))'
        ' or vector(0)'
    ),
    "p99_latency_ms": (
        'histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket'
        '{{service_name="{svc}",span_kind="SPAN_KIND_SERVER"}}[2m])) by (le))'
    ),
    "cpu_usage": (
        'sum(rate(container_cpu_usage_seconds_total'
        '{{namespace="otel-demo",pod=~"{svc}-.*"}}[2m]))'
    ),
    "memory_usage": (
        'sum(container_memory_working_set_bytes{{namespace="otel-demo",pod=~"{svc}-.*"}})'
    ),
    "pod_restarts": (
        'max(increase(kube_pod_container_status_restarts_total'
        '{{namespace="otel-demo",pod=~"{svc}-.*"}}[5m])) or vector(0)'
    ),
}

# Composite Z-score baseline: dominant signal -> inferred fault type.
SIGNAL_TO_FAULT: dict[str, str] = {
    "error_rate": "http_abort",
    "p99_latency_ms": "high_latency",
    "cpu_usage": "cpu_stress",
    "memory_usage": "memory_stress",
    "pod_restarts": "pod_crash",
}

# LogQL templates. Loki labels services as `opentelemetry-demo/<svc>` (namespaced job) or
# bare `<svc>` depending on the SDK, so match both. LogQL regex is fully anchored.
LOKI_QUERIES: dict[str, str] = {
    "error_logs": '{{service_name=~"(opentelemetry-demo/)?{svc}"}} |~ "(?i)(error|exception|fail)"',
    "warn_logs": '{{service_name=~"(opentelemetry-demo/)?{svc}"}} |~ "(?i)warn"',
}
