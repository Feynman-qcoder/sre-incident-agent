---
incident_id: payment-network-partition-seed42
service: payment
fault_type: http_abort
root_cause_service: payment
root_cause_fault_type: dependency_failure
confidence: 0.72
created_at: 2026-09-18T12:00:10.706556+00:00
source_report: artifacts/demo-gate-c/scenarios/payment-network-partition-seed42/report.json
---

# payment-network-partition-seed42

**根因摘要**：A network partition isolating the payment service prevents checkout's outbound gRPC call to payment from ever completing, so checkout blocks until its deadline and the delay propagates upstream to frontend. Because the fault is at the network boundary, payment emits no server spans and its own request_rate, error_rate and resource metrics stay flat/normal (zero errors, normal CPU, zero restarts), ruling out in-process faults.

**修复建议**：
- Inspect and remove/roll back any NetworkPolicy or network-partition injection isolating the payment pods in namespace otel-demo to restore connectivity between checkout and payment.
- Disable/roll back the flagd flag reconciling on payment (the only k8s activity observed in the window) to clear any injected boundary fault.
- Restart the payment deployment pods to re-establish checkout→payment gRPC channels and clear stuck/aborted connection state.
- Verify recovery: confirm payment server-span request_rate returns to baseline and checkout p99 latency / frontend error_rate normalize.

**证据要点**：
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="payment",span_kind="SPAN_KIND_SERVER"}[2m])) or vec
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="payment",span_kind="SPAN_KIND_SERVER",status_code="
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"payment-.*"}[2m
- signal_type='metric' query_or_id='max(increase(kube_pod_container_status_restarts_total{namespace="otel-demo",pod=~"paym
- signal_type='k8s_event' query_or_id='Updated: Successfully update ObservedGeneration and FailedMessage of resource (coun
