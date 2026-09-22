---
incident_id: email-pod_crash-seed42
service: email
fault_type: pod_crash
root_cause_service: email
root_cause_fault_type: pod_crash
confidence: 0.86
created_at: 2026-09-18T11:58:48.767609+00:00
source_report: artifacts/demo-gate-c/scenarios/email-pod_crash-seed42/report.json
---

# email-pod_crash-seed42

**根因摘要**：The email container in pod email-7699887dd9-rnbxw is being killed and restarted in a crash/back-off loop: K8s events show the container is terminated because its 'container definition changed' and then repeatedly fails to restart (Back-off restarting failed container email), while its caller (checkout) shows zero error propagation and sibling leaf services remain nominal.

**修复建议**：
- Run 'kubectl describe pod email-7699887dd9-rnbxw -n otel-demo' to read the restart/back-off events and container exit codes and confirm the pod is in CrashLoopBackOff.
- Inspect the email container spec/ConfigMap for the recent 'container definition changed' trigger and roll back the change that forced repeated restarts.
- Investigate why the pause image 'gcr.io/google-containers/pause:latest' cannot be pulled (ErrImagePull/ImagePullBackOff) to eliminate collateral pod instability.
- After remediation, verify email pod stability via kube_pod_container_status_restarts_total and confirm checkout email-send calls complete without errors.

**证据要点**：
- signal_type='k8s_event' query_or_id='BackOff: Back-off restarting failed container email in pod email-7699887dd9-rnbxw_o
- signal_type='k8s_event' query_or_id='Killing: Container email definition changed, will be restarted (count=2)' observed_
- signal_type='metric' query_or_id='max(increase(kube_pod_container_status_restarts_total{namespace="otel-demo",pod=~"emai
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="checkout",span_kind="SPAN_KIND_SERVER",status_code=
- signal_type='log' query_or_id='{service_name="email"} |= "error"' observed_value='no logs found for email in the window 
