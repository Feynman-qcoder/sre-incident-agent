---
incident_id: watchdog-KubeDeploymentReplicasMismatch-fa7c76e6
service: checkout
fault_type: pod_crash
root_cause_service: checkout
root_cause_fault_type: pod_crash
confidence: 0.92
created_at: 2026-09-17T09:54:49.644887+00:00
source_report: artifacts/watchdog-golden-e2e-cloud/reports/20260917T095449Z_KubeDeploymentReplicasMismatch_checkout.json
---

# watchdog-KubeDeploymentReplicasMismatch-fa7c76e6

**根因摘要**：A deployment spec change killed the checkout container ('Container checkout definition changed, will be restarted'), and the replacement container in pod checkout-5df89485f4-sjwdb cannot start because the image pull fails with DeadlineExceeded, leaving the pod in ImagePullBackOff / crash-loop back-off. The unavailable replica is the direct cause of the KubeDeploymentReplicasMismatch alert and the collapse of checkout traffic (~0.07 req/s).

**修复建议**：
- Roll back the checkout Deployment to the previous working container definition — the kill event 'Container checkout definition changed, will be restarted' shows a recent spec change triggered the outage.
- Fix the image pull failure: the pull of gcr.io/google-containers/pause:latest fails with DeadlineExceeded — verify registry connectivity/DNS, use an accessible mirror or pre-pulled image, or set imagePullPolicy: IfNotPresent.
- Delete the stuck pod checkout-5df89485f4-sjwdb (in ImagePullBackOff) once the image issue is resolved so the ReplicaSet creates a healthy replacement and replicas match desired state.
- Verify recovery: confirm deployment replicas match, checkout request rate returns to baseline, and frontend error_rate returns to ~0.
- Add alerting on ErrImagePull/ImagePullBackOff events and gate rollout on image pull pre-checks to catch this failure mode earlier.

**证据要点**：
- {'signal_type': 'k8s_event', 'query_or_id': 'Killing: Container checkout definition changed, will be restarted', 'observ
- {'signal_type': 'k8s_event', 'query_or_id': 'Failed: Error: ImagePullBackOff', 'observed_value': 'ImagePullBackOff (coun
- {'signal_type': 'k8s_event', 'query_or_id': 'BackOff: Back-off restarting failed container checkout in pod checkout-5df8
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(calls_total{service_name="checkout",span_kind="SPAN_KIND_SERVER"}[2m]
