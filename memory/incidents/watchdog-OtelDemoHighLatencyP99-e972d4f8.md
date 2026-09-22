---
incident_id: watchdog-OtelDemoHighLatencyP99-e972d4f8
service: payment
fault_type: high_latency
root_cause_service: payment
root_cause_fault_type: high_latency
confidence: 0.82
created_at: 2026-09-17T14:25:09.555089+00:00
source_report: artifacts/watchdog-golden-e2e-cloud-deepseek/reports/20260917T142509Z_OtelDemoHighLatencyP99_email.json
---

# watchdog-OtelDemoHighLatencyP99-e972d4f8

**根因摘要**：The payment service is a leaf dependency exhibiting a flat ~10s (10000ms) p99 server latency with no errors, normal CPU and memory, and no restarts. This injected latency propagates upstream, driving checkout, frontend and frontend-proxy to the same 10000ms p99 ceiling.

**修复建议**：
- Inspect the payment service deployment/config for an injected latency fault (e.g., flagd latency fault or artificial sleep) and remove/disable it.
- Restart or roll back the payment service pods to clear the faulted state, then verify payment p99 returns below 100ms.
- Add/verify client-side timeouts and circuit breakers between checkout and payment so a slow payment dependency cannot stall checkout and drag frontend p99 to the 10s ceiling.
- Monitor payment p99 and checkout p99 dashboards to confirm recovery and prevent recurrence.

**证据要点**：
- {'signal_type': 'metric', 'query_or_id': 'histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{span_kind="SPAN
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"payment
- {'signal_type': 'metric', 'query_or_id': 'sum(container_memory_working_set_bytes{namespace="otel-demo",pod=~"payment-.*"
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(calls_total{span_kind="SPAN_KIND_SERVER",status_code="STATUS_CODE_ERR
- {'signal_type': 'trace', 'query_or_id': '1934428e7faa572e', 'observed_value': 'user_checkout_single trace duration=34117
