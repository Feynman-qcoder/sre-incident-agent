---
incident_id: watchdog-OtelDemoHighLatencyP99-985567ae
service: product-catalog
fault_type: high_latency
root_cause_service: product-catalog
root_cause_fault_type: high_latency
confidence: 0.62
created_at: 2026-09-17T14:18:23.343641+00:00
source_report: artifacts/watchdog-golden-e2e-cloud-deepseek/reports/20260917T141823Z_OtelDemoHighLatencyP99_product-catalog.json
---

# watchdog-OtelDemoHighLatencyP99-985567ae

**根因摘要**：product-catalog, a leaf dependency called by frontend, checkout and recommendation, shows its server p50/p95/p99 pinned at the 10000ms ceiling with zero error traffic, so the added latency originates at this service and propagates to all upstream callers.

**修复建议**：
- Inspect the product-catalog deployment for an injected/configured latency fault (flagd feature flags, env/config, or a recently changed code path) and roll it back or reset the flag.
- Verify product-catalog pod resource limits and scheduling for CPU throttling or cgroup pressure even though container CPU (0.003) and working-set memory (~24MB) metrics were flat; also check for network/DNS delay to the catalog backend.
- Restart/roll the product-catalog pods once the fault source is identified to clear any stuck state, then confirm p99 returns to tens of ms.
- Add or verify timeouts and circuit breakers on upstream callers (checkout, recommendation, frontend) so a slow catalog does not pin their p99 at the 10s ceiling.
- Monitor checkout, recommendation and frontend p99 after the fix to confirm the upward-propagated latency anomaly clears.

**证据要点**：
- {'signal_type': 'metric', 'query_or_id': 'histogram_quantile(0.99, sum(rate(duration_milliseconds_bucket{service_name="p
- {'signal_type': 'trace', 'query_or_id': 'search_traces(service_name=product-catalog, min_duration_ms=5000)', 'observed_v
- {'signal_type': 'log', 'query_or_id': '{service_name="product-catalog"} |= "error"', 'observed_value': 'no logs found', 
