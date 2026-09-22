---
incident_id: watchdog-OtelDemoHighClientErrorRate-11ae2a2b
service: ad
fault_type: http_abort
root_cause_service: frontend
root_cause_fault_type: high_latency
confidence: 0.60
created_at: 2026-09-18T10:32:42.224082+00:00
source_report: artifacts/watchdog/20260918T103241Z_OtelDemoHighClientErrorRate_ad.json
---

# watchdog-OtelDemoHighClientErrorRate-11ae2a2b

**根因摘要**：The frontend exhibits a severe latency regression: its user-facing server spans are pinned at 15-30s (p95_duration=30753ms) with zero errors, indicating requests are held open by a slow dependency rather than failing fast. CPU (0.118 cores), memory (~613MB) and restart count (0) are all nominal, ruling out resource or pod-fault causes.

**修复建议**：
- Fetch the full span tree for trace 47f64c4e715ec886 (user_add_to_cart, 30000ms) and 152a1e56af4acd8d (user_get_recommendations, 15000ms) to identify the exact child span contributing the 15000ms stall and its owning service.
- Compare per-service p99 server latency for frontend's downstreams (recommendation, product-catalog, cart, shipping, currency, payment, ad) to isolate the single slow dependency.
- Review and tighten frontend request/upstream timeouts so a slow downstream cannot pin user requests at 15-30s; add circuit-breaking/deadline propagation.
- Check frontend and candidate downstream pods for CPU throttling/resource limits and inter-node network latency.
- Investigate k8s events on the quote/shipping path ('Killing: Container quote definition changed, will be restarted' and pause-image ImagePullBackOff) to confirm whether they impact checkout latency.

**证据要点**：
- signal_type='trace' query_or_id='47f64c4e715ec886' observed_value='user_add_to_cart=30000ms; search_traces(frontend, err
- signal_type='trace' query_or_id='152a1e56af4acd8d' observed_value='user_get_recommendations=15000ms (ok); 51f3db064c6be8
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="frontend",span_kind="SPAN_KIND_SERVER",status_code=
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"frontend-.*"}[2
- signal_type='metric' query_or_id='max(increase(kube_pod_container_status_restarts_total{namespace="otel-demo",pod=~"fron
