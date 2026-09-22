---
incident_id: quote-high_latency-seed42
service: quote
fault_type: high_latency
root_cause_service: quote
root_cause_fault_type: high_latency
confidence: 0.78
created_at: 2026-09-18T11:59:36.103470+00:00
source_report: artifacts/demo-gate-c/scenarios/quote-high_latency-seed42/report.json
---

# quote-high_latency-seed42

**根因摘要**：The quote service (leaf dependency of shipping) is the origin: its server request rate is zero and its p99 latency histogram yields no samples across the window, while error rate is flat and the pod stays alive with no crash/OOM events — indicating requests are stuck in-flight due to an injected latency fault rather than failing or crashing. That stall propagates up shipping → checkout → frontend, where checkout p99 saturates at 10000 ms.

**修复建议**：
- Inspect the quote pod for an injected latency fault (tc/netem delay or application-level sleep) — it stays alive with flat error rate and no restart/OOM events yet completes zero requests.
- Capture shipping→quote client-side spans and add a quote client-latency histogram so the blocked dependency becomes directly measurable.
- Temporarily add a request timeout / circuit breaker on the shipping→quote call path to stop the stall from saturating checkout (p99=10000 ms).
- Verify recovery by confirming quote server request rate returns to non-zero and checkout p99 drops well below 10000 ms.

**证据要点**：
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="quote",span_kind="SPAN_KIND_SERVER"}[2m])) or vecto
- signal_type='metric' query_or_id='histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="quote",sp
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="quote",span_kind="SPAN_KIND_SERVER",status_code="ST
- signal_type='k8s_event' query_or_id='get_pod_events namespace=otel-demo pod_name_prefix=quote since_seconds=600' observe
