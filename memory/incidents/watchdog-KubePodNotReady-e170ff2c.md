---
incident_id: watchdog-KubePodNotReady-e170ff2c
service: email
fault_type: pod_crash
root_cause_service: email
root_cause_fault_type: pod_crash
confidence: 0.60
created_at: 2026-09-18T08:12:50.901129+00:00
source_report: artifacts/watchdog/20260918T081250Z_KubePodNotReady_email.json
---

# watchdog-KubePodNotReady-e170ff2c

**根因摘要**：The email pod became NotReady: its container definition was changed and the container was killed for restart, and the recreated pod's sandbox failed to pull the pause image (ErrImagePull/ImagePullBackOff), so the pod could not reach Ready state within the incident window.

**修复建议**：
- Inspect the email deployment change that triggered 'Container email definition changed' and roll back to the last known-good revision if unintended (kubectl rollout undo deploy/email -n otel-demo).
- Verify node/kubelet connectivity to the registry for gcr.io/google-containers/pause:latest; investigate the DeadlineExceeded pull failure and retry the sandbox pull.
- Pre-pull or cache the sandbox image on the node, or configure a registry mirror/local cache so pod sandbox creation does not depend on a remote pull.
- Once the image is pullable, delete the stuck NotReady email pod so it is recreated cleanly (kubectl delete pod -n otel-demo email-7699887dd9-rnbxw).
- Confirm the email pod returns to Ready and monitor pod readiness / calls_total for email after recovery.

**证据要点**：
- signal_type='k8s_event' query_or_id='Killing: Container email definition changed, will be restarted' observed_value='cou
- signal_type='k8s_event' query_or_id='BackOff: Back-off pulling image "gcr.io/google-containers/pause:latest"' observed_v
- signal_type='k8s_event' query_or_id='Failed: Error: ImagePullBackOff' observed_value='count=4' expected_baseline='0 Imag
- signal_type='metric' query_or_id='max by (pod) (increase(kube_pod_container_status_restarts_total{namespace="otel-demo"}
