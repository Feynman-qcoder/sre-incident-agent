---
incident_id: watchdog-KubePodNotReady-195e11da
service: checkout
fault_type: pod_crash
root_cause_service: checkout
root_cause_fault_type: pod_crash
confidence: 0.92
created_at: 2026-09-16T13:45:57.549679+00:00
source_report: artifacts/watchdog-e2e-cloud/reports/20260916T134557Z_KubePodNotReady_572wp.json
---

# watchdog-KubePodNotReady-195e11da

**根因摘要**：The checkout container was killed for a definition change ('Container checkout definition changed, will be restarted') and the pod cannot become ready because the sandbox pause image gcr.io/google-containers/pause:latest fails to pull (DeadlineExceeded -> ErrImagePull -> ImagePullBackOff). The pod is stuck NotReady, collapsing checkout traffic to near-zero with 100% of remaining requests erroring and no container logs being emitted.

**修复建议**：
- Fix the image pull failure for gcr.io/google-containers/pause:latest: verify node egress/registry connectivity, configure imagePullSecrets or a registry mirror, or pre-pull/cache the pause image on the otel-demo worker nodes.
- Review the checkout container definition change that triggered the 'Killing ... will be restarted' event; roll back the rollout (kubectl rollout undo deployment/checkout -n otel-demo) if the change is faulty.
- Once the image pulls successfully, force a pod restart (kubectl rollout restart deployment/checkout -n otel-demo) and verify the pod reaches Ready with kubectl get pods -n otel-demo.
- Monitor checkout request_rate/error_rate and CPU usage to confirm traffic recovery, and add a readiness gate/alert on ImagePullBackOff to catch this failure mode earlier.

**证据要点**：
- {'signal_type': 'k8s_event', 'query_or_id': 'Killing: Container checkout definition changed, will be restarted (count=2)
- {'signal_type': 'k8s_event', 'query_or_id': 'Failed: Error: ImagePullBackOff (count=3)', 'observed_value': 'ImagePullBac
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"checkou
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(calls_total{service_name="checkout",span_kind="SPAN_KIND_SERVER"}[2m]
- {'signal_type': 'log', 'query_or_id': '{service_name="checkout"} |= "error"', 'observed_value': 'no logs found — contain
