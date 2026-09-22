---
incident_id: watchdog-OtelDemoTelemetryAbsent-3fa4f1b3
service: quote
fault_type: pod_crash
root_cause_service: product-catalog
root_cause_fault_type: pod_crash
confidence: 0.55
created_at: 2026-09-18T13:49:21.239510+00:00
source_report: artifacts/watchdog/20260918T134920Z_OtelDemoTelemetryAbsent_quote.json
---

# watchdog-OtelDemoTelemetryAbsent-3fa4f1b3

**根因摘要**：The product-catalog pod served nothing for the entire window: its server-span request rate is flat zero with no request or error logs, and its container CPU sits idle at ~0.001 cores versus ~0.281 for the healthy frontend. No restarts or K8s events were observed, indicating the pod/process was not handling traffic. As the central leaf dependency of frontend, checkout and recommendation, its loss produced the namespace-wide telemetry blackout and multi-second caller timeouts without application errors.

**修复建议**：
- Confirm product-catalog pod health and history: kubectl get pods -n otel-demo -l app.kubernetes.io/name=product-catalog and kubectl describe pod <product-catalog-pod> to inspect restart count, termination reason and last state.
- Inspect whether the pod was killed (Killing/Stopping container) and whether a chaos/pod-kill fault is injected against product-catalog; stop the fault injection if present.
- Restart/redeploy the product-catalog deployment and verify its server-span request rate returns to a non-zero baseline and container CPU rises off idle.
- After recovery, validate that frontend/checkout/recommendation latency returns to sub-second and that namespace span telemetry resumes.

**证据要点**：
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="product-catalog",span_kind="SPAN_KIND_SERVER"}[2m])
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"product-catalog
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="product-catalog",span_kind="SPAN_KIND_SERVER",statu
- signal_type='log' query_or_id='{service_name="product-catalog"}' observed_value='[no logs found] — zero request or error
- signal_type='k8s_event' query_or_id='get_pod_events(namespace=otel-demo, pod_name_prefix=product-catalog, since_seconds=
