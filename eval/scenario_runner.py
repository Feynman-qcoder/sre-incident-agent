"""Evaluation scenario runner.

Orchestrates: snapshot → run_agent(ReplayDataSource) → grounding verify → score.
Can also run baselines-only mode.

Usage (via Makefile):
    python -m eval.scenario_runner --scenario-dir scenarios/mvp --mode replay
    python -m eval.scenario_runner --scenario-dir scenarios/mvp --mode baselines-only
    python -m eval.scenario_runner --scenario-dir scenarios/mvp --mode all
    python -m eval.scenario_runner --snapshot-dir snapshots/foo --mode single --print-report
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

log = structlog.get_logger()

_ARTIFACTS_DIR = Path("artifacts")
_SNAPSHOTS_DIR = Path("snapshots")


def run_scenario(
    snapshot_dir: Path,
    mode: str = "replay",
    run_id: str = "",
) -> dict[str, object]:
    """Run one scenario: agent (or baseline) + grounding verify + per-scenario metrics."""
    from eval.grounding_verifier import verify
    from eval.metrics import ScenarioResult, compute_per_scenario
    from src.agent.schemas import InvestigationReport
    from src.datasources.replay import ReplayDataSource

    gt_path = snapshot_dir / "ground_truth.json"
    if not gt_path.exists():
        raise FileNotFoundError(f"ground_truth.json not found in {snapshot_dir}")

    with open(gt_path) as f:
        ground_truth: dict[str, str] = json.load(f)

    scenario_id = ground_truth.get("scenario_id", snapshot_dir.name)
    log.info("running_scenario", scenario_id=scenario_id, mode=mode)

    ds = ReplayDataSource(snapshot_dir)

    # Read window from metadata
    meta_path = snapshot_dir / "metadata.json"
    with open(meta_path) as f:
        meta = json.load(f)
    start = meta["window_start"]
    end = meta["window_end"]
    namespace = meta.get("namespace", "otel-demo")

    if mode == "baselines-only":
        return _run_baselines(ground_truth, ds, start, end, namespace, scenario_id, run_id)

    # Run agent (replay 与 all 共用；all 在 agent 完成后继续对同一 ds 跑基线)
    from src.agent.graph import build_graph
    from src.agent.memory import maybe_retrieve_and_build
    from src.agent.schemas import initial_state

    # add-incident-memory：检索键 = 场景元数据（ground truth 的 fault_service/fault_type）。
    # ⚠️ 设计含义（design D5 + 指令定稿）：replay 评测用 oracle 键 = 记忆命中的
    # 最坏情况压力测试——若记忆污染（提前收敛/跳过取证）在这里最先暴露。
    # 这是有意设计，不是 bug；INCIDENT_MEMORY=off 时空注入，行为与变更前一致。
    gt_service = str(ground_truth.get("fault_service", ""))
    gt_fault = str(ground_truth.get("fault_type", ""))
    hint_block, _hit = maybe_retrieve_and_build(gt_service, gt_fault)

    graph = build_graph(
        ds,
        # add-tool-gateway：审计落 run 目录（无 run_id 的 single 模式 → tmp）
        audit_path=(f"artifacts/{run_id}/scenarios/{scenario_id}/tool_audit.jsonl"
                    if run_id else None),
    )
    state = initial_state(
        incident_id=scenario_id,
        incident_start_ts=start,
        incident_end_ts=end,
        affected_namespace=namespace,
        memory_hint=hint_block,
    )
    state["_investigation_start_ts"] = datetime.now(UTC).isoformat()

    result = graph.invoke(state)
    report: InvestigationReport = result["final_report"]
    tool_calls_log: list[dict] = result.get("tool_calls_log", [])

    # Grounding verification (harness, not self-reported)
    grounding_result = verify(report, tool_calls_log)
    report.grounding_score = grounding_result.grounding_score

    sr = ScenarioResult(
        scenario_id=scenario_id,
        report=report,
        ground_truth=ground_truth,
        grounding_score=grounding_result.grounding_score,
    )
    per_scenario = compute_per_scenario(sr)

    # Save run artifacts
    if run_id:
        artifact_dir = _ARTIFACTS_DIR / run_id / "scenarios" / scenario_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        with open(artifact_dir / "report.json", "w") as f:
            f.write(report.model_dump_json(indent=2))
        with open(artifact_dir / "tool_calls.jsonl", "w") as f:
            for tc in tool_calls_log:
                f.write(json.dumps(tc) + "\n")
        with open(artifact_dir / "grounding.json", "w") as f:
            json.dump({
                "grounding_score": grounding_result.grounding_score,
                "verified": grounding_result.verified_count,
                "total": grounding_result.total_count,
                "failed_items": grounding_result.failed_items,
                "has_hallucination_warning": grounding_result.has_hallucination_warning,
            }, f, indent=2)

    if grounding_result.has_hallucination_warning:
        log.warning("hallucination_warning", scenario_id=scenario_id,
                    grounding_score=grounding_result.grounding_score)

    # add-incident-memory：writer（oracle 键：GT service/fault_type 作为记忆触发键，
    # 与检索键对称；失败仅告警）
    try:
        from src.agent.memory import memory_enabled, write_incident
        if memory_enabled():
            report._memory_service = gt_service
            report._memory_fault_type = gt_fault
            write_incident(report, f"artifacts/{run_id}/scenarios/{scenario_id}/report.json"
                          if run_id else f"(in-memory:{scenario_id})")
    except Exception as e:  # noqa: BLE001 — 记忆写入永不影响评测主流程
        log.warning("memory_write_gate_failed", scenario_id=scenario_id, error=repr(e)[:150])

    if mode == "all":
        # fix-eval-cross-run D2：同一 run_scenario() 调用内、同一个已构造的 ds 实例上
        # 跑 3 条 baseline——快照只加载一次，窗口/namespace 同源，同一性由代码结构保证。
        # baseline 纯读 ds（各自 predict），不写文件不建图零 LLM，与 agent 无状态互污（D3）。
        baselines = _run_baselines(ground_truth, ds, start, end, namespace, scenario_id, run_id)
        return {"agent": per_scenario, **baselines}

    return {"agent": per_scenario}


def _run_baselines(
    ground_truth: dict[str, str],
    ds: object,
    start: str,
    end: str,
    namespace: str,
    scenario_id: str,
    run_id: str,
) -> dict[str, object]:
    from eval.baselines.composite_zscore import CompositeZScoreBaseline
    from eval.baselines.random_baseline import RandomBaseline
    from eval.baselines.zscore_baseline import ZScoreBaseline
    from eval.metrics import ScenarioResult, compute_per_scenario

    baselines = {
        "random": RandomBaseline(seed=int(os.getenv("RANDOM_SEED", "42"))),
        "zscore": ZScoreBaseline(),
        "composite_zscore": CompositeZScoreBaseline(),
    }

    results: dict[str, object] = {}
    for name, baseline in baselines.items():
        report = baseline.predict(ds, start, end, namespace, scenario_id)  # type: ignore[arg-type]
        # Baselines have no tool_calls_log — grounding_score is 0 (they don't produce evidence)
        report.grounding_score = 0.0
        sr = ScenarioResult(
            scenario_id=scenario_id,
            report=report,
            ground_truth=ground_truth,
            grounding_score=0.0,
        )
        results[name] = compute_per_scenario(sr)

    return results


def run_all(
    scenario_dir: Path,
    mode: str,
    run_id: str = "",
) -> None:
    """Run all scenarios in a directory and write aggregated results."""
    if not run_id:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    # Find snapshot directories — use scenario_id from YAML metadata, fallback to stem
    snapshot_dirs: list[Path] = []
    for scenario_yaml in sorted(scenario_dir.glob("*.yaml")):
        try:
            import yaml as _yaml
            with open(scenario_yaml) as f:
                doc = _yaml.safe_load(f)
            scenario_id = str(doc.get("metadata", {}).get("scenario_id", scenario_yaml.stem))
        except Exception:
            scenario_id = scenario_yaml.stem
        snap_dir = _SNAPSHOTS_DIR / scenario_id
        if snap_dir.exists() and (snap_dir / "ground_truth.json").exists():
            snapshot_dirs.append(snap_dir)
        else:
            log.warning("snapshot_missing", scenario=scenario_id,
                        hint=f"Run: make fault SCENARIO={scenario_yaml}")

    if not snapshot_dirs:
        log.error("no_snapshots_found", scenario_dir=str(scenario_dir))
        sys.exit(1)

    log.info("running_eval", n_scenarios=len(snapshot_dirs), mode=mode, run_id=run_id)

    all_results: list[dict[str, object]] = []
    for snap_dir in snapshot_dirs:
        try:
            result = run_scenario(snap_dir, mode=mode, run_id=run_id)
            all_results.append({"snapshot_dir": str(snap_dir), **result})
        except Exception as e:
            log.error("scenario_failed", snapshot_dir=str(snap_dir), error=str(e))
            all_results.append({"snapshot_dir": str(snap_dir), "error": str(e)})

    # Compute aggregate metrics
    _write_summary(all_results, run_id, mode)


def _write_summary(
    all_results: list[dict[str, object]],
    run_id: str,
    mode: str,
) -> None:

    artifact_dir = _ARTIFACTS_DIR / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Write raw results
    with open(artifact_dir / "raw_results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    # If agent mode: rehydrate ScenarioResult objects for aggregate metrics
    # (simplified: read grounding from per-scenario files)
    # all 模式同样走此分支（照常打印 agent 表；基线数值进 raw_results.json 由 compare 消费）
    if mode != "baselines-only":
        scenario_results: list[dict] = [
            r.get("agent", {}) for r in all_results if "agent" in r
        ]
        _print_table(scenario_results, "Agent", run_id)

    config = {
        "run_id": run_id,
        "mode": mode,
        "model": os.getenv("NIM_MODEL", "deepseek-flash"),
        "seed": int(os.getenv("RANDOM_SEED", "42")),
        "agent_version": "0.1.0",
        "n_scenarios": len(all_results),
        "ts": datetime.now(UTC).isoformat(),
    }
    with open(artifact_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    log.info("eval_complete", run_id=run_id, artifact_dir=str(artifact_dir))
    print(f"\nArtifacts written to: artifacts/{run_id}/")


def _print_table(results: list[dict], label: str, run_id: str) -> None:
    if not results:
        return
    n = len(results)
    acc1 = sum(r.get("accuracy_at_1", 0) for r in results) / n
    acc3 = sum(r.get("accuracy_at_3", 0) for r in results) / n
    mrr = sum(r.get("mrr", 0.0) for r in results) / n
    ft = sum(r.get("fault_type_correct", 0) for r in results) / n
    gs = sum(r.get("grounding_score", 0.0) for r in results) / n
    lat = sum(r.get("latency_s", 0.0) for r in results) / n
    cost = sum(r.get("cost_usd", 0.0) for r in results)

    print(f"\n{'─'*70}")
    print(f"  {label} — {n} scenarios  [run_id: {run_id}]")
    print(f"{'─'*70}")
    print(f"  Acc@1:           {acc1:.3f}")
    print(f"  Acc@3:           {acc3:.3f}")
    print(f"  MRR:             {mrr:.3f}")
    print(f"  FaultType Acc:   {ft:.3f}")
    print(f"  Grounding Score: {gs:.3f}")
    print(f"  Mean Latency:    {lat:.1f}s")
    print(f"  Total Cost:      ${cost:.4f}")
    print(f"{'─'*70}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run evaluation scenarios")
    parser.add_argument("--scenario-dir", type=Path, default=Path("scenarios/mvp"))
    parser.add_argument("--snapshot-dir", type=Path, default=None,
                        help="Single snapshot dir (use with --mode single)")
    parser.add_argument("--mode", choices=["replay", "baselines-only", "single", "all"],
                        default="replay")
    parser.add_argument("--run-id", default="", help="Override run ID")
    parser.add_argument("--print-report", action="store_true")
    args = parser.parse_args()

    if args.mode == "single" and args.snapshot_dir:
        run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        result = run_scenario(args.snapshot_dir, mode="replay", run_id=run_id)
        if args.print_report:
            print(json.dumps(result, indent=2))
    else:
        run_all(args.scenario_dir, mode=args.mode, run_id=args.run_id)


if __name__ == "__main__":
    main()
