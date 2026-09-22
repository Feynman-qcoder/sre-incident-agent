---
incident_id: watchdog-OtelDemoHighErrorRate-5da54298
service: checkout
fault_type: http_abort
root_cause_service: checkout
root_cause_fault_type: high_latency
confidence: 0.62
created_at: 2026-09-18T10:38:50.937398+00:00
source_report: artifacts/watchdog/20260918T103850Z_OtelDemoHighErrorRate_checkout.json
---

# watchdog-OtelDemoHighErrorRate-5da54298

**根因摘要**：Checkout's server-side latency is pinned at the 10s histogram ceiling (p50=p95=p99=10000ms) for the entire window while its error rate, CPU and restart counts remain at baseline. Frontend inherits the elevated latency because it calls checkout on the purchase flow. The HighErrorRate alert name is misleading; this is a latency regression, not an error/abort fault.

**修复建议**：
- Break down checkout server spans by child dependency (cart, payment, shipping, currency, product-catalog, email) to identify the internal call adding multi-second latency.
- Inspect flagd feature-flag configuration active during the window and disable any latency/fault-injection flag affecting checkout (and frontend).
- Add a latency SLO alert on checkout p99 rather than relying solely on the HighErrorRate alert, since errors stayed at baseline while latency saturated.
- After the responsible flag/egress is disabled, verify checkout and frontend p99 latency returns below 100ms/500ms respectively.

**证据要点**：
- signal_type='metric' query_or_id='histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="checkout"
- signal_type='metric' query_or_id='histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="frontend"
- signal_type='trace' query_or_id='89377bdf2afa5e85' observed_value='checkout trace 89377bdf2afa5e85 (user_browse_product)
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="checkout",span_kind="SPAN_KIND_SERVER",status_code=
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"checkout-.*"}[2
