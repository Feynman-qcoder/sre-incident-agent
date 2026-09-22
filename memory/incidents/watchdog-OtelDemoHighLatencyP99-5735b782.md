---
incident_id: watchdog-OtelDemoHighLatencyP99-5735b782
service: ad
fault_type: high_latency
root_cause_service: recommendation
root_cause_fault_type: high_latency
confidence: 0.40
created_at: 2026-09-18T08:19:45.252746+00:00
source_report: artifacts/watchdog/20260918T081944Z_OtelDemoHighLatencyP99_ad.json
---

# watchdog-OtelDemoHighLatencyP99-5735b782

**根因摘要**：recommendation exhibits a saturated p99 latency pinned at the 10000 ms ceiling for the entire window, with a single trace p95_duration of ~5672504 ms, which cascades into frontend (its caller) also pinning at 10000 ms. Peer services (cart, ad) remain in the single-digit-to-low-ms range, isolating the anomaly to the recommendation path.

**修复建议**：
- Confirm the latency fault on recommendation (or its shared downstream product-catalog): inspect per-call span durations via search_traces to find which handler is sleeping and check for a chaos/flagd fault toggle.
- If a latency fault was injected, disable/roll back the fault and verify recommendation and frontend p99 return to baseline (<100 ms).
- Check cgroup CPU throttling on product-catalog (container_cpu_cfs_throttled_seconds_total) and, if it is the source, raise its CPU limit and/or scale replicas.
- Add/verify per-call deadlines, timeouts, and circuit breakers on frontend→recommendation and recommendation→product-catalog so a single slow dependency cannot cascade a 10 s p99 ceiling to the entry service.
- Re-sweep error_rate, cpu_usage, memory_usage and pod_restarts across all main services to fully rule out concurrent faults on checkout, cart, payment, shipping, currency and ad.

**证据要点**：
- signal_type='metric' query_or_id='histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="recommend
- signal_type='trace' query_or_id='6b78776609921bba' observed_value='search_traces(service_name=recommendation): 20 traces
