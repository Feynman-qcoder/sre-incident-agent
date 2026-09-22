"""Regenerate the deterministic test fixture snapshot.

Produces a tiny, synthetic-but-schema-accurate snapshot under snapshot-fixture/ using the
CANONICAL query templates (src/telemetry_queries.py) and v2 service names. `checkout` is made
anomalous on error_rate + pod_restarts (a pod_crash), so the Z-score baselines localise it.

Run: python tests/fixtures/generate_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.telemetry_queries import LOKI_QUERIES, METRIC_QUERIES  # noqa: E402

OUT = Path(__file__).parent / "snapshot-fixture"
SERVICES = ["frontend", "checkout", "cart", "payment"]
WINDOW_START = "2024-01-15T13:59:00+00:00"
WINDOW_END = "2024-01-15T14:06:00+00:00"
BASELINE_START = "2024-01-15T13:29:00+00:00"  # window_start - 30 min
_TS = [1705327140.0, 1705327170.0, 1705327200.0]

# Normal (fault_mean, baseline_mean) per signal; checkout overrides with a crash signature.
_NORMAL = {"error_rate": 0.0, "request_rate": 1.5, "p99_latency_ms": 50.0,
           "cpu_usage": 0.05, "memory_usage": 1.0e8, "pod_restarts": 0.0}
_ANOMALY = {"checkout": {"error_rate": 0.92, "pod_restarts": 3.0, "request_rate": 0.1}}


def _series(value: float) -> list[dict]:
    return [{"metric": {}, "values": [[ts, str(value)] for ts in _TS]}]


def _prom_entries() -> list[dict]:
    out: list[dict] = []
    for svc in SERVICES:
        for sig, tpl in METRIC_QUERIES.items():
            q = tpl.format(svc=svc)
            fault = _ANOMALY.get(svc, {}).get(sig, _NORMAL[sig])
            base = _NORMAL[sig] if sig not in ("error_rate", "pod_restarts") else 0.0
            out.append({"type": "range", "query": q, "start": WINDOW_START,
                        "end": WINDOW_END, "step": "30s", "result": _series(fault)})
            out.append({"type": "range", "query": q, "start": BASELINE_START,
                        "end": WINDOW_START, "step": "30s", "is_baseline": True,
                        "result": _series(base)})
    return out


def _traces() -> list[dict]:
    return [
        {"traceID": "t-checkout-err-1", "rootServiceName": "checkout",
         "durationMs": 1200, "hasError": True},
        {"traceID": "t-checkout-ok-1", "rootServiceName": "checkout",
         "durationMs": 80, "hasError": False},
        {"traceID": "t-frontend-1", "rootServiceName": "frontend",
         "durationMs": 300, "hasError": True},
    ]


def _loki() -> list[dict]:
    q = LOKI_QUERIES["error_logs"].format(svc="checkout")
    return [{"logql": q, "start": WINDOW_START, "end": WINDOW_END,
             "result": [{"stream": {"service_name": "opentelemetry-demo/checkout"},
                         "values": [[str(int(ts * 1e9)), "error: connection refused"]
                                    for ts in _TS]}]}]


def _events() -> list[dict]:
    return [
        {"type": "Warning", "reason": "Killing", "message": "Stopping container checkout",
         "count": 1, "involved_object_name": "checkout-abc123"},
        {"type": "Normal", "reason": "Started", "message": "Started container checkout",
         "count": 1, "involved_object_name": "checkout-abc123"},
        {"type": "Normal", "reason": "Pulled", "message": "Container image present",
         "count": 1, "involved_object_name": "frontend-def456"},
    ]


def _metadata() -> dict:
    from src.datasources.live import _STATIC_TOPOLOGY
    return {"snapshot_ts": WINDOW_END, "window_start": WINDOW_START, "window_end": WINDOW_END,
            "namespace": "otel-demo", "services_snapshotted": SERVICES,
            "service_topology": dict(_STATIC_TOPOLOGY)}


def _ground_truth() -> dict:
    return {"scenario_id": "checkout-pod_crash-seed42", "fault_service": "checkout",
            "fault_type": "pod_crash", "chaos_kind": "PodChaos",
            "injection_ts": "2024-01-15T14:00:00+00:00",
            "recovery_ts": "2024-01-15T14:05:00+00:00", "seed": 42,
            "chaos_manifest_hash": "fixturehash01", "window_start": WINDOW_START,
            "window_end": WINDOW_END, "validation_passed": True}


def main() -> None:
    for sub in ("prometheus", "tempo", "loki", "k8s"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    (OUT / "prometheus" / "raw_queries.json").write_text(json.dumps(_prom_entries(), indent=2))
    (OUT / "tempo" / "trace_summaries.json").write_text(json.dumps(_traces(), indent=2))
    (OUT / "loki" / "raw_queries.json").write_text(json.dumps(_loki(), indent=2))
    (OUT / "k8s" / "events.json").write_text(json.dumps(_events(), indent=2))
    (OUT / "metadata.json").write_text(json.dumps(_metadata(), indent=2))
    (OUT / "ground_truth.json").write_text(json.dumps(_ground_truth(), indent=2))
    print(f"fixture written to {OUT}")


if __name__ == "__main__":
    main()
