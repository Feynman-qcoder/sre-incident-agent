"""CLI entry point for the SRE-Copilot agent.

Usage (live mode):
    python -m src.agent.run \\
        --incident-id inc-001 \\
        --start 2024-01-15T14:00:00Z \\
        --end 2024-01-15T14:10:00Z \\
        --namespace otel-demo

Usage (replay mode):
    python -m src.agent.run \\
        --incident-id inc-001 \\
        --start 2024-01-15T14:00:00Z \\
        --end 2024-01-15T14:10:00Z \\
        --snapshot-dir snapshots/checkoutservice-pod_crash-seed42
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog
from dotenv import load_dotenv

load_dotenv()

log = structlog.get_logger()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SRE-Copilot: investigate a K8s incident")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--start", required=True, help="ISO-8601 UTC incident start")
    parser.add_argument("--end", required=True, help="ISO-8601 UTC incident end")
    parser.add_argument("--namespace", default=os.getenv("K8S_NAMESPACE", "otel-demo"))
    parser.add_argument("--snapshot-dir", default=None,
                        help="Replay from snapshot dir instead of live cluster")
    parser.add_argument("--output", default=None,
                        help="Write report JSON to this file (default: stdout)")
    args = parser.parse_args(argv)

    # Select data source
    if args.snapshot_dir:
        from src.datasources.replay import ReplayDataSource
        ds = ReplayDataSource(args.snapshot_dir)
        log.info("mode", type="replay", snapshot_dir=args.snapshot_dir)
    else:
        from src.datasources.live import LiveDataSource
        ds = LiveDataSource()
        log.info("mode", type="live")

    # Build and run graph
    from src.agent.graph import build_graph
    from src.agent.schemas import initial_state

    graph = build_graph(ds)

    state = initial_state(
        incident_id=args.incident_id,
        incident_start_ts=args.start,
        incident_end_ts=args.end,
        affected_namespace=args.namespace,
    )
    state["_investigation_start_ts"] = datetime.now(UTC).isoformat()

    log.info("investigation_start", incident_id=args.incident_id)
    result = graph.invoke(state)
    report = result.get("final_report")

    if report is None:
        log.error("no_report_produced")
        sys.exit(1)

    report_json = report.model_dump_json(indent=2)

    if args.output:
        Path(args.output).write_text(report_json)
        log.info("report_written", path=args.output)
    else:
        print(report_json)

    log.info(
        "investigation_complete",
        incident_id=args.incident_id,
        top_service=report.root_causes[0].service if report.root_causes else "none",
        top_fault_type=report.fault_type_classification,
        latency_s=report.latency_s,
        cost_usd=report.cost_usd,
    )


if __name__ == "__main__":
    main()
