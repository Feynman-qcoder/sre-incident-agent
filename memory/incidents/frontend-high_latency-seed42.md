---
incident_id: frontend-high_latency-seed42
service: frontend
fault_type: high_latency
root_cause_service: product-catalog
root_cause_fault_type: high_latency
confidence: 0.62
created_at: 2026-09-18T11:59:11.906932+00:00
source_report: artifacts/demo-gate-c/scenarios/frontend-high_latency-seed42/report.json
---

# frontend-high_latency-seed42

**根因摘要**：product-catalog sits on the shared downstream hot path of frontend (also used by checkout and recommendation per topology). Its degraded request handling pins the frontend server-span p99 to a hard 10000 ms ceiling across the entire window, coupled with a strong CPU burn on the catalog pods (~1.93 cores vs ~0.015 cores on frontend pods), with no errors and no restarts — a classic injected latency/CPU-saturation signature on the shared hot path.

**修复建议**：
- Inspect product-catalog pods for injected chaos (latency/stress sidecars, pod annotations, events) and confirm the ~1.93-core CPU burn via `kubectl top pod -n otel-demo`; remove the injected fault once identified.
- Verify product-catalog CPU requests/limits and check for cgroup CPU throttling; if the saturation is organic, raise limits or scale replicas, since product-catalog is the shared hot path for frontend, checkout and recommendation.
- Validate recovery by re-checking the frontend server-span p99 latency against the 10s ceiling and the product-catalog CPU rate once the fault is removed.

**证据要点**：
- signal_type='metric' query_or_id='histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="frontend"
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"product-catalog
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"frontend-.*"}[2
