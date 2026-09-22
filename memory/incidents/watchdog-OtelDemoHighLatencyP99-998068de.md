---
incident_id: watchdog-OtelDemoHighLatencyP99-998068de
service: product-catalog
fault_type: high_latency
root_cause_service: product-catalog
root_cause_fault_type: cpu_stress
confidence: 0.82
created_at: 2026-09-18T04:58:51.771603+00:00
source_report: artifacts/oncall-e2e-cloud/20260918T045851Z_OtelDemoHighLatencyP99_frontend.json
---

# watchdog-OtelDemoHighLatencyP99-998068de

**根因摘要**：product-catalog is burning 1-2 CPU cores (mean 0.952, max 2.149) while serving a very low request rate (~0.22 req/s), indicating injected CPU stress rather than organic load. The saturated CPU inflates response latency, driving p99 to the 10000ms ceiling and propagating to frontend and checkout which depend on it.

**修复建议**：
- Confirm CPU stress on product-catalog by checking for a stress-ng / CPU-burn process inside the product-catalog pods.
- Disable or reset the faulty flagd fault-injection flag targeting product-catalog (CPU stress) to restore normal CPU and latency.
- If the fault is not injection-based, add CPU limits/requests and increase replicas for product-catalog to shed the CPU saturation.
- Verify recovery by re-checking product-catalog p99 latency (<50ms) and CPU usage (<0.05 cores), then confirm frontend/checkout p99 returns to baseline.
- Add alerting on product-catalog CPU saturation vs. request rate to distinguish stress from organic load.

**证据要点**：
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"product
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(calls_total{service_name="product-catalog",span_kind="SPAN_KIND_SERVE
- {'signal_type': 'metric', 'query_or_id': 'histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="p
- {'signal_type': 'trace', 'query_or_id': 'ada9012c00553803', 'observed_value': 'product-catalog trace p95_duration=600033
