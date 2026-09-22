---
incident_id: watchdog-OtelDemoHighLatencyP99-b699fe05
service: shipping
fault_type: high_latency
root_cause_service: shipping
root_cause_fault_type: high_latency
confidence: 0.82
created_at: 2026-09-17T14:32:36.425743+00:00
source_report: artifacts/watchdog-golden-e2e-cloud-deepseek/reports/20260917T143236Z_OtelDemoHighLatencyP99_shipping.json
---

# watchdog-OtelDemoHighLatencyP99-b699fe05

**根因摘要**：The shipping service exhibits an injected/abnormal processing latency: its server-span p99 jumped to ~9.2s (vs ~2ms baseline) with a wide p50/p95 spread, while its own downstream (quote) and all other dependencies stayed normal. The delay originates in shipping itself and propagates upstream to checkout and frontend.

**修复建议**：
- Confirm a latency fault-injection / feature flag is active on the shipping service (check flagd and shipping deployment config for an injected delay) and disable it to restore baseline.
- Roll back or restart the shipping Deployment/pods to clear any injected delay, then verify shipping server-span p99 returns to ~2ms.
- If shipping latency is not a deliberate injection, profile the shipping container (blocking I/O, DNS, or downstream quote client timeouts) since quote server latency remains normal.
- Add an SLO alert on shipping p99 and a circuit-breaker/timeout around checkout→shipping so checkout is not blocked by a slow shipping dependency.
- Verify checkout and frontend p99 recover as a downstream effect once shipping is fixed.

**证据要点**：
- {'signal_type': 'metric', 'query_or_id': 'histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="s
- {'signal_type': 'metric', 'query_or_id': 'histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="q
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(calls_total{service_name="shipping",span_kind="SPAN_KIND_SERVER",stat
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"shippin
- {'signal_type': 'metric', 'query_or_id': 'max(increase(kube_pod_container_status_restarts_total{namespace="otel-demo",po
