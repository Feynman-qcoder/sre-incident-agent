---
incident_id: watchdog-OtelDemoHighLatencyP99-b47b613b
service: cart
fault_type: high_latency
root_cause_service: cart
root_cause_fault_type: high_latency
confidence: 0.82
created_at: 2026-09-17T14:49:50.654075+00:00
source_report: artifacts/watchdog-golden-e2e-cloud-deepseek/reports/20260917T144950Z_OtelDemoHighLatencyP99_cart.json
---

# watchdog-OtelDemoHighLatencyP99-b47b613b

**根因摘要**：Cart service shows a sharp p99 latency spike (~72ms, p50 ~3ms) during the incident window while all peer leaf services remained at ~2-10ms. No error-rate increase, CPU/memory pressure, or pod crashes were observed, indicating an injected latency fault localized to cart.

**修复建议**：
- Inspect cart service for injected latency (e.g., flagd feature flag / chaos latency injection targeting cart) and disable the fault flag.
- Verify cart application-level processing time and any downstream/store calls for added delays; compare cart span durations against historical baseline.
- Monitor cart p99 latency after remediation to confirm return to ~2-3ms and ensure upstream checkout/frontend latency normalizes.
- Add alerting on per-service p99 latency deviations to catch localized latency injections earlier.

**证据要点**：
- {'signal_type': 'metric', 'query_or_id': 'histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="c
- {'signal_type': 'trace', 'query_or_id': '128bd6d780126db8', 'observed_value': "cart 'order-consumed' span at 23674ms; se
- {'signal_type': 'k8s_event', 'query_or_id': 'Started: Container started (count=3)', 'observed_value': 'cart pod containe
