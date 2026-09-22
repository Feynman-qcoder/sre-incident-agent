---
incident_id: watchdog-KubePodNotReady-3d474e83
service: checkout
fault_type: pod_crash
root_cause_service: checkout
root_cause_fault_type: pod_crash
confidence: 0.78
created_at: 2026-09-18T05:02:42.202997+00:00
source_report: artifacts/oncall-e2e-cloud/20260918T050242Z_KubePodNotReady_checkout.json
---

# watchdog-KubePodNotReady-3d474e83

**根因摘要**：The checkout pod (checkout-5df89485f4-5ptgq) is stuck NotReady because its container repeatedly fails to start: the sandbox image gcr.io/google-containers/pause:latest cannot be pulled (ErrImagePull/ImagePullBackOff), and the checkout container is placed into a restart back-off, so the pod never becomes Ready and serves no traffic.

**修复建议**：
- Inspect the checkout Deployment (checkout-5df89485f4) to determine why the sandbox image gcr.io/google-containers/pause:latest fails to pull (registry reachability, imagePullSecrets, rate limiting).
- Restore the image pull path or pre-seed/mirror the pause image on otel-sre-copilot-control-plane and update the sandbox image reference if gcr.io is unreachable.
- Delete the stuck pod checkout-5df89485f4-5ptgq so it is recreated once the image is resolvable, and confirm the pod reaches Ready.
- Add/keep an alert on ErrImagePull/ImagePullBackOff and KubePodNotReady for otel-demo pods to catch this class of failure earlier.

**证据要点**：
- {'signal_type': 'k8s_event', 'query_or_id': 'Failed: Error: ImagePullBackOff (count=4)', 'observed_value': 'ImagePullBac
- {'signal_type': 'k8s_event', 'query_or_id': 'BackOff: Back-off restarting failed container checkout in pod checkout-5df8
- {'signal_type': 'k8s_event', 'query_or_id': 'Failed: Failed to pull image "gcr.io/google-containers/pause:latest": rpc e
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(calls_total{service_name="checkout",span_kind="SPAN_KIND_SERVER",stat
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"checkou
