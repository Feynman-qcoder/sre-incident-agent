---
incident_id: recommendation-cpu_stress-seed42
service: recommendation
fault_type: cpu_stress
root_cause_service: recommendation
root_cause_fault_type: cpu_stress
confidence: 0.92
created_at: 2026-09-18T06:00:52.079973+00:00
source_report: artifacts/mem-inject-on/scenarios/recommendation-cpu_stress-seed42/report.json
---

# recommendation-cpu_stress-seed42

**根因摘要**：The recommendation service pod is consuming an anomalous amount of CPU (mean 2.343 cores, peaking at 3.608 cores) during the incident window, roughly 30-1200x higher than peer services (frontend 0.070, checkout 0.003, cart 0.007, product-catalog 0.025), which is characteristic of injected CPU stress. Error rate, memory, restarts and p99 latency remain at baseline, ruling out http_abort, memory_stress, pod_crash and high_latency.

**修复建议**：
- Confirm the CPU saturation source on the recommendation pod (kubectl top pods -n otel-demo; inspect for a stress-ng / busy-loop sidecar or injected fault marked seed42).
- If the fault is injected, stop/disable the CPU-stress experiment targeting recommendation (e.g. remove the chaos/fault injection) and verify CPU returns to baseline (~0.05 cores).
- Verify recommendation p99 latency and downstream product-catalog call rates return to baseline after the CPU stress is removed.

**证据要点**：
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"recommendation-
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"frontend-.*"}[2
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"checkout-.*"}[2
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"cart-.*"}[2m]))
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"product-catalog
