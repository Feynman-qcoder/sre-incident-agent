---
incident_id: watchdog-OtelDemoHighLatencyP99-a46af510
service: checkout
fault_type: high_latency
root_cause_service: checkout
root_cause_fault_type: high_latency
confidence: 0.86
created_at: 2026-09-17T14:31:44.054566+00:00
source_report: artifacts/watchdog-golden-e2e-cloud-deepseek/reports/20260917T143144Z_OtelDemoHighLatencyP99_checkout.json
---

# watchdog-OtelDemoHighLatencyP99-a46af510

**根因摘要**：The checkout service exhibits an isolated server-side p99 latency spike (up to ~1950ms) while every peer service remains under ~26ms. No errors, CPU/memory pressure, or pod restarts accompany it, so the latency is injected/in-process rather than caused by resource exhaustion or a failing dependency.

**修复建议**：
- Confirm the latency fault on checkoutservice: check any chaos/flagd fault injection targeting checkoutservice in otel-demo and disable/revert it.
- Inspect the slow checkout spans (e.g. user_checkout_multi ~1.2s, order-consumed ~10-48s) to identify the internal stage introducing the delay (e.g. injected network/latency delay vs. a slow blocking call).
- Since CPU/memory/restarts/errors are all normal, rule out resource scaling and focus on injected delay removal; re-measure checkout p99 to verify return to <50ms.
- Add/verify a p99 latency SLO alert scoped per-service so latency regressions on a single service are caught even when upstream/downstream peers look healthy.

**证据要点**：
- {'signal_type': 'metric', 'query_or_id': 'histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="c
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(calls_total{service_name="checkout",span_kind="SPAN_KIND_SERVER",stat
- {'signal_type': 'trace', 'query_or_id': 'search_traces(service_name=checkout, min_duration_ms=500)', 'observed_value': "
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"checkou
- {'signal_type': 'metric', 'query_or_id': 'sum(container_memory_working_set_bytes{namespace="otel-demo",pod=~"checkout-.*
