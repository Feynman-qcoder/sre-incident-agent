---
incident_id: watchdog-OtelDemoHighLatencyP99-c2dddb31
service: product-catalog
fault_type: high_latency
root_cause_service: product-catalog
root_cause_fault_type: high_latency
confidence: 0.60
created_at: 2026-09-18T04:59:44.130046+00:00
source_report: artifacts/oncall-e2e-cloud/20260918T045944Z_OtelDemoHighLatencyP99_.json
---

# watchdog-OtelDemoHighLatencyP99-c2dddb31

**根因摘要**：product-catalog, the deepest shared dependency of frontend/checkout/recommendation, shows server-side p99 latency saturated at 10000ms (p50 also 10000ms) with no errors, CPU, or restart anomalies. This pure latency saturation propagates to recommendation (→product-catalog), checkout (→product-catalog), and frontend (→product-catalog/recommendation/checkout), exactly matching the affected service set.

**修复建议**：
- Restart/redeploy the product-catalog deployment to clear the induced latency (e.g. kubectl rollout restart deployment/product-catalog -n otel-demo).
- Inspect product-catalog's backing datastore/DB latency and connection-pool health, since product-catalog is a leaf service whose server-side latency saturates at 10000ms.
- Scale product-catalog replicas and enable request timeouts / circuit breakers on callers (recommendation, checkout, frontend) to bound blast radius while the root cause is fixed.
- Verify recovery by re-checking product-catalog p99 (should return to single-digit ms) and confirming recommendation/checkout/frontend p99 normalize.
- Add/confirm an alert on product-catalog server-side p99 latency to catch saturation earlier.

**证据要点**：
- {'signal_type': 'metric', 'query_or_id': 'histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="p
- {'signal_type': 'trace', 'query_or_id': 'service_name=product-catalog, min_duration_ms=5000 (search_traces): 20 total, 0
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"product
- {'signal_type': 'log', 'query_or_id': '{service_name="product-catalog"} |= "error"', 'observed_value': 'no logs found', 
- {'signal_type': 'k8s_event', 'query_or_id': 'Scheduled: Successfully assigned otel-demo/product-catalog-5bb7676754-hcfpv
