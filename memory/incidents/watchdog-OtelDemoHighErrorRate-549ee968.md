---
incident_id: watchdog-OtelDemoHighErrorRate-549ee968
service: frontend
fault_type: http_abort
root_cause_service: frontend
root_cause_fault_type: high_latency
confidence: 0.66
created_at: 2026-09-21T11:26:16.944941+00:00
source_report: artifacts/watchdog/20260921T112616Z_OtelDemoHighErrorRate_frontend.json
---

# watchdog-OtelDemoHighErrorRate-549ee968

**根因摘要**：The frontend edge service exhibits a severe p99 tail-latency spike (max ~7004 ms, approaching the ~7 s request timeout ceiling) while p50/p95 stay ~23-25 ms, so a subset of edge requests stall until they time out/abort, generating a sustained server-side error rate. All downstream dependencies report zero server errors, localizing the fault to the frontend edge (consistent with an injected latency/timeout fault).

**修复建议**：
- Audit the active flagd feature-flag configuration for a frontend latency/timeout injection flag and disable it to validate the root cause.
- Capture and inspect frontend request traces/logs during the latency window to identify the specific handler or downstream call stalling to the ~7s timeout.
- If no flag injection is found, add edge-side circuit-breaking/timeout tuning on frontend handlers (e.g. user_get_ads) and consider horizontal scaling of the frontend deployment to shed tail-latency stalls.
- Monitor frontend p99 latency and server error rate after mitigation to confirm p99 returns to < ~50ms and error_rate < 0.01.

**证据要点**：
- signal_type='metric' query_or_id='histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="frontend"
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="frontend",span_kind="SPAN_KIND_SERVER",status_code=
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="checkout",span_kind="SPAN_KIND_SERVER",status_code=
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="cart",span_kind="SPAN_KIND_SERVER",status_code="STA
- signal_type='trace' query_or_id='e6284f684c80a610' observed_value='frontend user_get_ads handler span = 1856ms (search_t
