---
incident_id: watchdog-OtelDemoHighLatencyP99-f919f10f
service: product-catalog
fault_type: high_latency
root_cause_service: product-catalog
root_cause_fault_type: high_latency
confidence: 0.72
created_at: 2026-09-18T05:00:48.463183+00:00
source_report: artifacts/oncall-e2e-cloud/20260918T050048Z_OtelDemoHighLatencyP99_recommendation.json
---

# watchdog-OtelDemoHighLatencyP99-f919f10f

**根因摘要**：product-catalog, a leaf dependency of recommendation/checkout/frontend, shows sustained server-side latency far above its ~2ms baseline for the entire incident window, with no errors, CPU, or memory pressure. This stalls every catalog browse and recommendation path and is the origin of the cluster-wide p99 latency spike.

**修复建议**：
- Confirm a latency chaos experiment (e.g. Chaos Mesh NetworkChaos/HTTPChaos with a busybox helper) is targeting the product-catalog pod; the busybox pull + container kill event is the injection marker.
- Remove/pause the chaos experiment on product-catalog and verify its server p99 returns to ~single-digit ms; watch recommendation/checkout/frontend p99 recover downstream within minutes.
- If the delay is not chaos-injected, inspect product-catalog's upstream data source (product DB / file load) for a slow dependency and add a request timeout + circuit breaker so a slow catalog cannot hang checkout/recommendation.
- Add latency SLO alerts on product-catalog p99 and on the frontend BrowseProduct/GetRecommendations endpoints to catch this leaf-level regression earlier.
- Tune recommendation's retry budget so a stalled product-catalog call cannot amplify to ~164s end-to-end traces.

**证据要点**：
- {'signal_type': 'metric', 'query_or_id': 'histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="p
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"product
- {'signal_type': 'metric', 'query_or_id': 'sum(container_memory_working_set_bytes{namespace="otel-demo",pod=~"product-cat
- {'signal_type': 'metric', 'query_or_id': 'max(increase(kube_pod_container_status_restarts_total{namespace="otel-demo",po
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(calls_total{service_name="product-catalog",span_kind="SPAN_KIND_SERVE
