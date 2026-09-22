---
incident_id: watchdog-OtelDemoHighClientErrorRate-d302b7b6
service: fraud-detection
fault_type: http_abort
root_cause_service: product-catalog
root_cause_fault_type: cpu_stress
confidence: 0.62
created_at: 2026-09-18T10:34:32.245702+00:00
source_report: artifacts/watchdog/20260918T103431Z_OtelDemoHighClientErrorRate_fraud-detection.json
---

# watchdog-OtelDemoHighClientErrorRate-d302b7b6

**根因摘要**：product-catalog sustained ~2.08 CPU cores (peak 2.33) versus 0.012-0.12 cores on every peer service, indicating severe CPU saturation on its pods. As the shared leaf dependency of frontend, checkout and recommendation, this resource starvation slows catalog lookups and propagates client-facing latency and errors upward to the frontend edge.

**修复建议**：
- Inspect product-catalog pod resource requests/limits and per-container CPU breakdown to confirm whether the ~2.1-core saturation is a runaway thread/GC loop or genuine load.
- Raise product-catalog CPU limits and/or horizontally scale the deployment (HPA) to absorb load and relieve downstream catalog call latency.
- Add p99-latency alerting on product-catalog and its callers (frontend, checkout, recommendation) to catch CPU-driven slowness before client errors surface.
- Verify no node-level autoscaling/quotas are capping product-catalog, since peers on the same node remain at <0.13 cores.

**证据要点**：
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"product-catalog
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="frontend",span_kind="SPAN_KIND_SERVER",status_code=
- signal_type='trace' query_or_id='90f0d1dc5c26d8bc' observed_value='p95_duration=30750ms; user_get_recommendations span 1
- signal_type='metric' query_or_id='max(increase(kube_pod_container_status_restarts_total{namespace="otel-demo",pod=~"prod
- signal_type='metric' query_or_id='sum(container_memory_working_set_bytes{namespace="otel-demo",pod=~"product-catalog-.*"
