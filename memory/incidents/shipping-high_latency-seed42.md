---
incident_id: shipping-high_latency-seed42
service: shipping
fault_type: high_latency
root_cause_service: shipping
root_cause_fault_type: high_latency
confidence: 0.88
created_at: 2026-09-18T06:01:29.737283+00:00
source_report: artifacts/mem-inject-on/scenarios/shipping-high_latency-seed42/report.json
---

# shipping-high_latency-seed42

**根因摘要**：The shipping service exhibits a severe server-side latency anomaly (p99 mean ~5.7s, peaking at 9650ms) while its error rate, CPU, memory, and pod restarts all remain normal and its only downstream dependency (quote) stays healthy at ~2ms. This isolates the fault to a latency injection within shipping itself rather than a dependency or resource-pressure issue; the delay propagates upstream to checkout.

**修复建议**：
- Confirm a latency fault-injection / feature flag is active on the shipping service (check flagd and shipping deployment config for an injected delay) and disable/rollback the fault flag.
- Restart the shipping Deployment/pods to clear any injected in-process delay, then verify shipping server-span p99 returns to ~2ms baseline.
- Verify downstream quote (~2ms) and upstream checkout/frontend latencies recover to baseline after the shipping fix.

**证据要点**：
- signal_type='metric' query_or_id='histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="shipping"
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="shipping",span_kind="SPAN_KIND_SERVER",status_code=
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"shipping-.*"}[2
- signal_type='metric' query_or_id='max(increase(kube_pod_container_status_restarts_total{namespace="otel-demo",pod=~"ship
- signal_type='metric' query_or_id='sum(container_memory_working_set_bytes{namespace="otel-demo",pod=~"shipping-.*"})' obs
