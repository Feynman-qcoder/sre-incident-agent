---
incident_id: cart-memory_stress-seed42
service: cart
fault_type: memory_stress
root_cause_service: cart
root_cause_fault_type: memory_stress
confidence: 0.82
created_at: 2026-09-18T06:01:10.473706+00:00
source_report: artifacts/mem-inject-on/scenarios/cart-memory_stress-seed42/report.json
---

# cart-memory_stress-seed42

**根因摘要**：The cart service experienced memory pressure during the incident window: its container working set (~93MB mean, peaking ~108MB) is roughly 4x peer services (~24MB for product-catalog and checkout), accompanied by a p99 latency spike and container recreation/restarts. This is the dominant anomaly matching the memory_stress fault.

**修复建议**：
- Disable the cart memory_stress fault via the fault-injection control plane (flagd) for the seed42 scenario.
- Inspect and raise the cart pod memory limits/requests, and investigate a possible memory leak — the cart working set (~93-108MB) ran ~4x its peer services.
- Verify cart container restart/recreation stops and p99 latency returns below 10ms after the fault is removed.
- Add alerting on cart container_memory_working_set_bytes relative to peer baseline and on container restart counts.

**证据要点**：
- signal_type='metric' query_or_id='sum(container_memory_working_set_bytes{namespace="otel-demo",pod=~"cart-.*"})' observe
- signal_type='metric' query_or_id='sum(container_memory_working_set_bytes{namespace="otel-demo",pod=~"product-catalog-.*"
- signal_type='metric' query_or_id='sum(container_memory_working_set_bytes{namespace="otel-demo",pod=~"checkout-.*"})' obs
- signal_type='metric' query_or_id='histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="cart",spa
- signal_type='metric' query_or_id='max(increase(kube_pod_container_status_restarts_total{namespace="otel-demo",pod=~"cart
