---
incident_id: frontend-pod_crash-seed42
service: frontend
fault_type: pod_crash
root_cause_service: frontend
root_cause_fault_type: pod_crash
confidence: 0.72
created_at: 2026-09-18T06:01:59.500174+00:00
source_report: artifacts/mem-inject-on/scenarios/frontend-pod_crash-seed42/report.json
---

# frontend-pod_crash-seed42

**根因摘要**：The frontend container was terminated ('Killing: Stopping container frontend') and replaced by a freshly scheduled pod frontend-76cbddfbcc-zm8l8, causing a collapse of frontend server request rate (p50 dropped to ~8 from a mean of ~148). No downstream service shows elevated errors, so the disruption originates at the frontend pod itself, consistent with a container crash/restart.

**修复建议**：
- Confirm frontend pod restart/crash: kubectl -n otel-demo get pods -l app=frontend and kubectl describe pod frontend-76cbddfbcc-zm8l8 (inspect Last State, Reason, Exit Code).
- Inspect the terminated frontend container's previous logs (kubectl logs <prior-frontend-pod> --previous) to distinguish OOMKill, liveness-probe kill, or application crash.
- Review frontend resource requests/limits and liveness/readiness probe thresholds; increase memory limit or relax probe timeouts if a kill was probe- or OOM-driven.
- Verify downstream calls (checkout, cart, recommendation, product-catalog) remained healthy and add pod-restart alerting on frontend to catch recurrence early.

**证据要点**：
- signal_type='k8s_event' query_or_id='Killing: Stopping container frontend (count=1)' observed_value='count=1 within inci
- signal_type='k8s_event' query_or_id='Scheduled: Successfully assigned otel-demo/frontend-76cbddfbcc-zm8l8 to otel-sre-co
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="frontend",span_kind="SPAN_KIND_SERVER"}[2m])) or ve
