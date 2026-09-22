---
incident_id: watchdog-KubePodNotReady-0e3c8389
service: quote
fault_type: pod_crash
root_cause_service: product-catalog
root_cause_fault_type: cpu_stress
confidence: 0.62
created_at: 2026-09-18T10:33:35.509011+00:00
source_report: artifacts/watchdog/20260918T103334Z_KubePodNotReady_quote.json
---

# watchdog-KubePodNotReady-0e3c8389

**根因摘要**：The product-catalog pod (product-catalog-5bb7676754-hcfpv) consumes ~2.1 CPU cores — roughly 20x every other otel-demo service pod — while remaining error-free, a classic CPU saturation signature. This starvation stalls request handling (multi-second to tens-of-seconds latencies) and most plausibly causes readiness probes to fail, marking the pod NotReady for the watchdog.

**修复建议**：
- Confirm CPU saturation on product-catalog: kubectl top pod -n otel-demo product-catalog-5bb7676754-hcfpv and compare actual CPU usage against its requests/limits.
- If a cpu_stress/CPU-burn fault is injected against product-catalog, stop the fault injection (or scale out replicas / raise CPU limits) to relieve core starvation.
- Review product-catalog readiness/liveness probe timeout and failure thresholds so transient CPU saturation does not mark the pod NotReady (KubePodNotReady).
- Investigate the quote pod recreation event and the image pull failures for gcr.io/google-containers/pause:latest; verify registry reachability, imagePullSecrets and pull policy.
- After remediation, re-run search_traces on product-catalog and re-check error_rate/duration histograms to confirm end-to-end latency recovery.

**证据要点**：
- signal_type='metric' query_or_id='sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="otel-demo"}[2m]))' obs
- signal_type='trace' query_or_id='search_traces(service_name=product-catalog, min_duration_ms=1000)' observed_value='20 t
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="product-catalog",span_kind="SPAN_KIND_SERVER",statu
