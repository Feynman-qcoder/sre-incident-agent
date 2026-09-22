---
incident_id: watchdog-OtelDemoHighErrorRate-3a0d3ec3
service: frontend
fault_type: http_abort
root_cause_service: frontend
root_cause_fault_type: http_abort
confidence: 0.60
created_at: 2026-09-21T10:02:46.786871+00:00
source_report: artifacts/watchdog/20260921T100246Z_OtelDemoHighErrorRate_.json
---

# watchdog-OtelDemoHighErrorRate-3a0d3ec3

**根因摘要**：The frontend service sustained a roughly 60% server-side error rate (error_rate ~1.24/s out of ~2.04 req/s) across the entire incident window, while every downstream dependency reported zero server errors. This isolates the fault to the frontend edge, consistent with an injected HTTP abort rather than downstream failure propagation.

**修复建议**：
- Inspect frontend logs/traces to identify the specific failing route and returned HTTP status to confirm abort vs. timeout (broaden the LogQL filter since {service_name="frontend"} |= "error" returned no lines).
- Audit the active flagd feature-flag configuration for a frontend/route failure or latency flag and disable it to validate the injection.
- Verify frontend→flagd EventStream connectivity and flagd pod health (get_pod_events for flagd) in case the 600 s streaming spans mask an evaluation stall.
- Roll back or restart the frontend deployment if the abort is not feature-flag driven, then monitor frontend error_rate and p99 latency for recovery.
- Add alerting on frontend error fraction (errors/requests) and p99 latency to catch edge-local faults that downstream error metrics miss.

**证据要点**：
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="frontend",span_kind="SPAN_KIND_SERVER",status_code=
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="frontend",span_kind="SPAN_KIND_SERVER"}[2m])) or ve
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="checkout",span_kind="SPAN_KIND_SERVER",status_code=
