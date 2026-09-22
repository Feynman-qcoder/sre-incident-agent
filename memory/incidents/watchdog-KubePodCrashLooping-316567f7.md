---
incident_id: watchdog-KubePodCrashLooping-316567f7
service: checkout
fault_type: pod_crash
root_cause_service: checkout
root_cause_fault_type: pod_crash
confidence: 0.92
created_at: 2026-09-16T13:50:16.888804+00:00
source_report: artifacts/watchdog-e2e-cloud/reports/20260916T135016Z_KubePodCrashLooping_572wp.json
---

# watchdog-KubePodCrashLooping-316567f7

**根因摘要**：The checkout container was repeatedly killed and restarted during the incident window (Killing/Started/Created events with counts 2-3), matching the KubePodCrashLooping alert. CPU (~0.001 cores) and memory (~34MB) stayed normal, ruling out resource exhaustion; the 'definition changed, will be restarted' event indicates a container spec change/rollout triggered the crash loop, compounded by ImagePullBackOff on the pause image blocking sandbox creation.

**修复建议**：
- Inspect the checkout pod with kubectl describe pod -n otel-demo <checkout-pod> and kubectl logs --previous to capture the crash reason; the 'definition changed, will be restarted' event points to a spec/rollout change as the trigger.
- If a recent deployment changed the checkout container spec, roll it back with kubectl rollout undo deployment/checkout -n otel-demo and verify the pod reaches Ready.
- Resolve the ImagePullBackOff on gcr.io/google-containers/pause:latest (pre-pull the image, fix registry access/timeout, or use a locally available pause image) so pod sandbox creation is not blocked during restarts.
- Add readiness and startup probes on checkout so it is removed from endpoints while crash-looping, producing fast failures instead of 15-54s hung requests.
- Add timeouts, retries with backoff, and a circuit breaker in frontend (and accounting/fraud-detection) calls to checkout to prevent cascading errors during checkout outages.

**证据要点**：
- {'signal_type': 'k8s_event', 'query_or_id': 'Killing: Container checkout definition changed, will be restarted (count=2)
- {'signal_type': 'k8s_event', 'query_or_id': 'Failed: Error: ImagePullBackOff (count=3)', 'observed_value': 'BackOff pull
- {'signal_type': 'metric', 'query_or_id': 'max(increase(kube_pod_container_status_restarts_total{namespace="otel-demo",po
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"checkou
- {'signal_type': 'metric', 'query_or_id': 'sum(container_memory_working_set_bytes{namespace="otel-demo",pod=~"checkout-.*
