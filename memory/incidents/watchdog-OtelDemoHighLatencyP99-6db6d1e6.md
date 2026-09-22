---
incident_id: watchdog-OtelDemoHighLatencyP99-6db6d1e6
service: flagd
fault_type: high_latency
root_cause_service: recommendation
root_cause_fault_type: high_latency
confidence: 0.62
created_at: 2026-09-18T10:36:26.080813+00:00
source_report: artifacts/watchdog/20260918T103625Z_OtelDemoHighLatencyP99_flagd.json
---

# watchdog-OtelDemoHighLatencyP99-6db6d1e6

**根因摘要**：Recommendation sits on the slow trace path (frontend -> recommendation -> product-catalog) with p95 trace duration ~30.75s and zero errors, while its CPU (~0.011 cores), memory (~193MB), restart count and error logs are all normal. checkout, which does not depend on recommendation, shows a distinctly lower p95 (~16.5s), isolating recommendation as the latency source rather than a shared downstream.

**修复建议**：
- Scale out the recommendation deployment (increase replicas and CPU/memory headroom) to relieve the ~30s request handling observed on its server spans.
- Instrument the recommendation -> product-catalog client-span path to confirm whether recommendation is blocked on a slow downstream call or is injecting latency itself.
- Add a synthetic probe / SLO alert directly on the recommendation service p99 latency so the originating service is flagged instead of only the cluster-wide frontend P99 watchdog.
- If latency persists without resource pressure, restart/roll out the recommendation pods to clear any stuck in-process state, and review the feature-flag (flagd) configuration for any flag causing slow evaluation.

**证据要点**：
- signal_type='trace' query_or_id='d7ffd04f4ae4e231' observed_value='recommendation trace path p95_duration=30751ms, 0 err
- signal_type='trace' query_or_id='f9eeb6e45b229d46' observed_value='checkout trace path has an individual span of 14999ms
- signal_type='metric' query_or_id='sum(rate(container_cpu_usage_seconds_total{namespace="otel-demo",pod=~"recommendation-
- signal_type='metric' query_or_id='sum(container_memory_working_set_bytes{namespace="otel-demo",pod=~"recommendation-.*"}
- signal_type='metric' query_or_id='sum(rate(calls_total{service_name="recommendation",span_kind="SPAN_KIND_SERVER",status
