---
incident_id: watchdog-OtelDemoHighLatencyP99-796321aa
service: payment
fault_type: high_latency
root_cause_service: payment
root_cause_fault_type: high_latency
confidence: 0.72
created_at: 2026-09-17T14:24:24.126817+00:00
source_report: artifacts/watchdog-golden-e2e-cloud-deepseek/reports/20260917T142424Z_OtelDemoHighLatencyP99_payment.json
---

# watchdog-OtelDemoHighLatencyP99-796321aa

**根因摘要**：The payment service, a leaf dependency with no downstream calls, shows intrinsic server-side p99 latency saturated at the 10s histogram ceiling, orders of magnitude above peer leaves (~2-9ms). This latency propagates up through checkout to frontend, producing the end-to-end user_checkout trace durations of 29-45s.

**修复建议**：
- Inspect the payment service for an injected latency fault (e.g., flagd feature-flag latency injection in the OTel demo) and disable it.
- Profile payment pod processing time (GC, thread contention, external calls); payment is a leaf so latency is intrinsic to the service.
- If latency is resource-driven, check payment CPU/memory limits and vertical-scale; current CPU (~0.006 cores) and RSS (~202 MB) look nominal, pointing to injected/app-level delay.
- Restart/redeploy payment pods to clear any stuck state and confirm p99 returns to single-digit ms.
- Verify recovery end-to-end by re-checking frontend and payment server p99 latency and user_checkout trace durations.

**证据要点**：
- {'signal_type': 'metric', 'query_or_id': 'histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="p
- {'signal_type': 'trace', 'query_or_id': "search_traces(service_name='payment', min_duration_ms=3000)", 'observed_value':
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"payment
- {'signal_type': 'metric', 'query_or_id': 'sum(rate(calls_total{service_name="payment",span_kind="SPAN_KIND_SERVER",statu
