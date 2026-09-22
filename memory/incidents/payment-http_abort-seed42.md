---
incident_id: payment-http_abort-seed42
service: payment
fault_type: http_abort
root_cause_service: payment
root_cause_fault_type: http_abort
confidence: 0.72
created_at: 2026-09-18T06:00:36.164192+00:00
source_report: artifacts/mem-inject-on/scenarios/payment-http_abort-seed42/report.json
---

# payment-http_abort-seed42

**根因摘要**：An http_abort fault on the payment service (a leaf dependency of checkout) causes checkout's outbound HTTP calls to payment to never complete normally, so checkout blocks until its 10s deadline. The abort occurs at the HTTP boundary, so payment emits no completed/errored server span and its own server-side latency and error metrics remain normal.

**修复建议**：
- Disable/roll back the http_abort fault injection on the payment service (the flagd flag controlling the payment HTTP abort) to restore normal responses.
- Restart the payment deployment pods to clear any stuck/aborted connection state and confirm checkout p99 latency returns below 100ms.
- Monitor checkout and frontend p99 latency for recovery to baseline (<100ms and <500ms respectively); add a per-dependency timeout/circuit-breaker on checkout→payment so a hung dependency fails fast instead of blocking to the 10s deadline.

**证据要点**：
- signal_type='metric' query_or_id='histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="checkout"
- signal_type='metric' query_or_id='histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="frontend"
- signal_type='metric' query_or_id='histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="payment",
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="payment",span_kind="SPAN_KIND_SERVER",status_code="
