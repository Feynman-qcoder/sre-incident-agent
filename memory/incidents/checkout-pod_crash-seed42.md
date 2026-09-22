---
incident_id: checkout-pod_crash-seed42
service: checkout
fault_type: pod_crash
root_cause_service: checkout
root_cause_fault_type: pod_crash
confidence: 0.86
created_at: 2026-09-18T05:59:57.054062+00:00
source_report: artifacts/mem-inject-on/scenarios/checkout-pod_crash-seed42/report.json
---

# checkout-pod_crash-seed42

**根因摘要**：The checkout container was killed ('Container checkout definition changed, will be restarted'), and the replacement pod cannot start because its sandbox image gcr.io/google-containers/pause:latest fails to pull with DeadlineExceeded, leaving the pod in ErrImagePull/ImagePullBackOff. As a result checkout serves no traffic (server request rate collapses to ~0) and its callers (frontend, accounting, fraud-detection) are impacted.

**修复建议**：
- Confirm checkout pod state: kubectl get pods -n otel-demo -l app=checkout and check for ImagePullBackOff / ErrImagePull and restart counts.
- Roll back the checkout Deployment to the previous working container definition — the kill event 'Container checkout definition changed, will be restarted' shows a recent spec change triggered the outage.
- Fix the sandbox/pause image pull path: the pull of gcr.io/google-containers/pause:latest fails with DeadlineExceeded — verify registry connectivity/DNS, use an accessible mirror or pre-pulled image, or set imagePullPolicy: IfNotPresent.
- Once the pod becomes Ready, verify recovery by confirming checkout server request rate returns to baseline and frontend error rate drops below 0.01.

**证据要点**：
- signal_type='k8s_event' query_or_id='Killing: Container checkout definition changed, will be restarted (count=1)' observ
- signal_type='k8s_event' query_or_id='Failed: Failed to pull image "gcr.io/google-containers/pause:latest": rpc error: co
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="checkout",span_kind="SPAN_KIND_SERVER"}[2m])) or ve
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="checkout",span_kind="SPAN_KIND_SERVER",status_code=
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="frontend",span_kind="SPAN_KIND_SERVER",status_code=
