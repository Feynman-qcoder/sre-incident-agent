---
incident_id: watchdog-KubeDeploymentReplicasMismatch-88f37cbc
service: checkout
fault_type: pod_crash
root_cause_service: checkout
root_cause_fault_type: pod_crash
confidence: 0.92
created_at: 2026-09-16T13:48:33.715712+00:00
source_report: artifacts/watchdog-e2e-cloud/reports/20260916T134833Z_KubeDeploymentReplicasMismatch_state.json
---

# watchdog-KubeDeploymentReplicasMismatch-88f37cbc

**根因摘要**：The checkout container was killed ('Container checkout definition changed, will be restarted') and replacement pods could never become Ready because the sandbox pause image gcr.io/google-containers/pause:latest failed to pull (DeadlineExceeded -> ErrImagePull -> ImagePullBackOff). With pods unavailable, the checkout Deployment's available replicas fell below desired, firing KubeDeploymentReplicasMismatch; checkout served near-zero traffic (request_rate ~0.01 req/s, CPU ~0.002 cores) during the window.

**修复建议**：
- Fix the image pull failure for gcr.io/google-containers/pause:latest (pre-pull/cache the pause image on nodes, or point the pod sandbox image at an accessible registry/mirror) so replacement checkout pods can start.
- Review and roll back or correct the checkout deployment definition change that triggered the container kills ('Container checkout definition changed, will be restarted').
- Verify the checkout Deployment returns to its desired replica count and is Ready (kubectl -n otel-demo rollout status deployment/checkout), then confirm request_rate and CPU recover.
- Monitor frontend p99 latency and error_rate until they return to baseline once checkout is serving traffic again.
- Add alerting on ErrImagePull/ImagePullBackOff and KubeDeploymentReplicasMismatch with faster notification to catch pod-startup failures before user impact.

**证据要点**：
- {'signal_type': 'k8s_event', 'query_or_id': 'Killing: Container checkout definition changed, will be restarted (count=2)
- {'signal_type': 'k8s_event', 'query_or_id': 'Failed: Error: ImagePullBackOff (count=3)', 'observed_value': '3 ImagePullB
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(calls_total{service_name="checkout",span_kind="SPAN_KIND_SERVER"}[2m]
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"checkou
