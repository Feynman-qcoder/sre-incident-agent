---
incident_id: product-catalog-high_latency-seed42
service: product-catalog
fault_type: high_latency
root_cause_service: product-catalog
root_cause_fault_type: high_latency
confidence: 0.90
created_at: 2026-09-18T06:00:13.587359+00:00
source_report: artifacts/mem-inject-on/scenarios/product-catalog-high_latency-seed42/report.json
---

# product-catalog-high_latency-seed42

**根因摘要**：product-catalog serves requests with a saturated p99 latency pinned at the ~10000ms ceiling while its error rate, CPU usage, memory usage and pod restart count all remain at normal baselines, indicating a sustained/injected latency fault rather than resource exhaustion, crashes or a failing downstream dependency. As a shared leaf dependency of frontend, checkout and recommendation, this latency propagates up the call graph to all upstream callers.

**修复建议**：
- Confirm and disable the injected latency fault on product-catalog (e.g. flagd fault-injection flag or network delay / tc netem rule for the seed42 scenario) and roll it back.
- Inspect product-catalog request handling for artificial sleeps or downstream I/O stalls; verify the ~10s delay is injected rather than a genuine backend slowdown.
- Restart/roll the product-catalog deployment to clear any stuck latency condition, then confirm p99 server latency returns below 100ms.
- Validate recovery by re-checking p99 latency for product-catalog and its dependents (frontend, checkout, recommendation) to ensure the propagated latency clears.

**证据要点**：
- signal_type='metric' query_or_id='histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="product-c
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="product-catalog",span_kind="SPAN_KIND_SERVER",statu
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"product-catalog
- signal_type='metric' query_or_id='sum(container_memory_working_set_bytes{namespace="otel-demo",pod=~"product-catalog-.*"
- signal_type='metric' query_or_id='max(increase(kube_pod_container_status_restarts_total{namespace="otel-demo",pod=~"prod
