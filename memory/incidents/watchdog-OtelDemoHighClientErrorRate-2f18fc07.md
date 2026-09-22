---
incident_id: watchdog-OtelDemoHighClientErrorRate-2f18fc07
service: payment
fault_type: http_abort
root_cause_service: product-catalog
root_cause_fault_type: cpu_stress
confidence: 0.60
created_at: 2026-09-18T10:32:07.237354+00:00
source_report: artifacts/watchdog/20260918T103206Z_OtelDemoHighClientErrorRate_payment.json
---

# watchdog-OtelDemoHighClientErrorRate-2f18fc07

**根因摘要**：product-catalog shows a severe, isolated CPU surge (~2.1 cores) while every peer service stays near-idle (<0.13 cores). Requests that depend on it (frontend browse_product, recommendation get_recommendations, checkout add_to_cart) block for 15-30s, so client-facing calls exceed their deadline and surface as watchdog client errors while server-side error counters stay at zero.

**修复建议**：
- Disable/roll back the cpu_stress (or equivalent latency) fault injection on the product-catalog service via its flagd flag and confirm product-catalog CPU returns to <0.2 cores.
- Restart the product-catalog deployment pods to clear any stuck/contended state and re-check that browse_product, get_recommendations and add_to_cart p99 durations drop below 500ms.
- Verify upstream impact clears: frontend and checkout client error rate returns to 0 and no spans are pinned at the 15s/30s deadline.
- Inspect the quote pod restart / pause-image ImagePullBackOff events as a secondary item and re-create the quote pod if shipping latency remains elevated.

**证据要点**：
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"product-catalog
- signal_type='trace' query_or_id='1eb85988567967ca' observed_value='user_add_to_cart duration=30003ms (ok, no error)' exp
- signal_type='trace' query_or_id='152a1e56af4acd8d' observed_value='user_get_recommendations duration=15000ms (ok, no err
