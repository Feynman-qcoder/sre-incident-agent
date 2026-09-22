"""Build the offline demo bundle — webui/bundle.js (window.__BUNDLE__ inline).

add-local-demo-pack D1：构建期聚合是唯一数据源——前端零逻辑取数、零造数
（一切数字来自磁盘产物；bundle 是聚合不是编造）。写 `bundle.js`（而非
bundle.json + fetch）彻底绕开 file:// 的 fetch 限制。

扫描三类产物：
1. 演示 run 白名单（DEMO_RUNS）——artifacts/ 下每个 run：config + raw_results +
   各场景 report/grounding/tool_calls/tool_audit；
2. snapshots/ 11 场景（GT + metadata + DEMO.md）；
3. scenarios/mvp/*.yaml（chaos 参数）。

用法：
    python webui/build_bundle.py            # 全量重建 bundle.js
    python webui/build_bundle.py --offline  # 同上（bundle 构建本就零 LLM；
                                             # 开关仅为 CLI 语义对齐 spec）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    import yaml
except ImportError:  # 唯一外部依赖：仅「场景」视图解析 scenarios/mvp/*.yaml 时需要
    print(
        "ERROR: 缺少 PyYAML（本脚本唯一外部依赖）。\n"
        "  安装：pip install pyyaml\n"
        "  替代：无需重建——仓库内已包含构建好的 webui/bundle.js，\n"
        "        直接双击 webui/index.html 即可查看完整四视图。",
        file=sys.stderr,
    )
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"

# 演示 run 白名单（design：只取指定 run 集合，全量产物仍留磁盘不进 bundle）
DEMO_RUNS = [
    "demo-gate-c",  # make demo-all 全链验证 run（最新）
    "batch1-seed42", "batch1-seed43", "batch1-seed44",
    "gw-regression",
    "mem-baseline-off", "mem-inject-on",
]

# 记忆对照素材（D5）：payment 双跑 tool_calls 时间线
MEMORY_COMPARE = {
    "scenario": "payment-http_abort-seed42",
    "off_run": "mem-baseline-off",
    "on_run": "mem-inject-on",
}


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                out.append(json.loads(ln))
    except OSError:
        pass
    return out


def _bundle_run(run_id: str) -> dict | None:
    d = ART / run_id
    if not d.exists():
        return None
    run: dict = {"run_id": run_id, "scenarios": {}}
    cfg = _read_json(d / "config.json")
    if isinstance(cfg, dict):
        run["config"] = {
            k: cfg.get(k) for k in
            ("mode", "model", "seed", "agent_version", "n_scenarios", "ts",
             "random_seed", "llm_model")
        }
    raw = _read_json(d / "raw_results.json")
    run["raw"] = raw if isinstance(raw, list) else []
    for sdir in sorted((d / "scenarios").glob("*/")) if (d / "scenarios").exists() else []:
        sid = sdir.name
        entry: dict = {}
        report = _read_json(sdir / "report.json")
        if isinstance(report, dict):
            entry["report"] = report
        grounding = _read_json(sdir / "grounding.json")
        if isinstance(grounding, dict):
            entry["grounding"] = grounding
        tcl = _read_jsonl(sdir / "tool_calls.jsonl")
        if tcl:
            entry["tool_calls"] = tcl
        audit = _read_jsonl(sdir / "tool_audit.jsonl")
        if audit:
            entry["tool_audit"] = audit
        if entry:
            run["scenarios"][sid] = entry
    # 平铺布局（oncall-e2e-cloud：报告 json 直接在 run 根，场景名从文件名解析）
    if not run["scenarios"]:
        for jf in sorted(d.glob("*.json")):
            if jf.name in {"config.json", "raw_results.json", "state.json", "ack_log.json"}:
                continue
            report = _read_json(jf)
            if not (isinstance(report, dict) and "root_causes" in report):
                continue
            sid = jf.stem
            run["scenarios"][sid] = {
                "report": report,
                "grounding": report.get("_grounding", {}),
                "flat_file": jf.name,
            }
            run.setdefault("config", {})["layout"] = "flat"
    return run if (run.get("scenarios") or run.get("raw")) else None


def _bundle_snapshots() -> list[dict]:
    out = []
    snaps = ROOT / "snapshots"
    if not snaps.exists():
        return out
    for sdir in sorted(snaps.iterdir()):
        if not sdir.is_dir():
            continue
        gt = _read_json(sdir / "ground_truth.json")
        meta = _read_json(sdir / "metadata.json")
        if not isinstance(gt, dict):
            continue
        demo_md = ""
        demo_path = sdir / "DEMO.md"
        if demo_path.exists():
            demo_md = demo_path.read_text(encoding="utf-8")
        out.append({
            "scenario_id": gt.get("scenario_id", sdir.name),
            "ground_truth": gt,
            "metadata": meta if isinstance(meta, dict) else {},
            "demo_md": demo_md,
            "telemetry_files": sorted(
                p.name for p in sdir.rglob("*") if p.is_file()
                and p.suffix in {".json", ".jsonl"}),
        })
    return out


def _bundle_scenarios() -> list[dict]:
    out = []
    for yml in sorted((ROOT / "scenarios" / "mvp").glob("*.yaml")):
        try:
            doc = yaml.safe_load(yml.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(doc, dict) and doc.get("metadata"):
            out.append({"file": yml.name, **doc})
    return out


def build_bundle() -> dict:
    runs = {}
    for rid in DEMO_RUNS:
        b = _bundle_run(rid)
        if b:
            runs[rid] = b
    # oncall 实录（真实事故报告集——调查台"真实事故"来源）
    oncall = _bundle_run("oncall-e2e-cloud")
    if oncall:
        runs["oncall-e2e-cloud"] = oncall

    snapshots = _bundle_snapshots()
    scenarios = _bundle_scenarios()

    bundle = {
        "generated_at": datetime.now(UTC).isoformat(),
        "demo_runs": DEMO_RUNS,
        "runs": runs,
        "snapshots": snapshots,
        "scenarios": scenarios,
        "memory_compare": {
            "scenario": MEMORY_COMPARE["scenario"],
            "off": _scenario_tool_summary(runs.get(MEMORY_COMPARE["off_run"], {}),
                                          MEMORY_COMPARE["scenario"]),
            "on": _scenario_tool_summary(runs.get(MEMORY_COMPARE["on_run"], {}),
                                         MEMORY_COMPARE["scenario"]),
        },
        "meta": {
            "n_runs": len(runs),
            "n_snapshots": len(snapshots),
            "n_scenarios": len(scenarios),
        },
    }
    return bundle


def _scenario_tool_summary(run: dict, sid: str) -> dict | None:
    sc = run.get("scenarios", {}).get(sid)
    if not sc:
        return None
    report = sc.get("report", {})
    tcl = sc.get("tool_calls", [])
    raw = next((r for r in run.get("raw", [])
                if sid in str(r.get("snapshot_dir", ""))), None)
    return {
        "run_id": run.get("run_id"),
        "tool_calls": [
            {"i": i, "tool": t.get("tool_name"), "query": t.get("query_or_id", "")[:80]}
            for i, t in enumerate(tcl)
        ],
        "n_tool_calls": len(tcl),
        "latency_s": raw.get("agent", {}).get("latency_s") if isinstance(raw, dict) else None,
        "grounding": raw.get("agent", {}).get("grounding_score") if isinstance(raw, dict) else None,
        "cost_usd": report.get("cost_usd"),
    }


def _persist_runs(added: list[str]) -> None:
    """把追加的 run 持久写回本文件的 DEMO_RUNS 列表末尾（追加语义，不触碰既有行）。

    锚点策略：定位 `DEMO_RUNS = [` ... `]` 的列表闭合处（正则），把新行插在 `]` 前——
    与既有行内容解耦，连续追加（第二次调用）同样命中。
    """
    import re as _re
    src_path = Path(__file__)
    text = src_path.read_text(encoding="utf-8")
    m = _re.search(r"DEMO_RUNS = \[(.*?)\n\]", text, _re.S)
    if not m:
        raise RuntimeError("DEMO_RUNS 列表未找到——本文件结构已变，请人工检查")
    if f'"{added[0]}"' in m.group(1):
        raise RuntimeError("run 已在白名单（调用方应已去重）")
    new_lines = "".join(f'    "{rid}",  # --add-run 追加\n' for rid in added)
    new_text = text[:m.end(1)] + "\n" + new_lines.rstrip("\n") + text[m.end(1):]
    src_path.write_text(new_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build webui/bundle.js from disk artifacts")
    parser.add_argument("--offline", action="store_true",
                        help="bundle build is inherently LLM-free (spec P4 semantics)")
    parser.add_argument("--add-run", action="append", default=[], metavar="RUN_ID",
                        help="追加 run 到演示白名单并重建 bundle（可多次；追加语义——旧 run 不动，"
                             "白名单持久写回本文件 DEMO_RUNS 末尾）")
    args = parser.parse_args(argv)

    # --add-run：校验存在性 → 持久追加白名单（旧 run 零改动）→ 继续走正常重建
    global DEMO_RUNS
    if args.add_run:
        added = []
        for rid in args.add_run:
            if not (ART / rid).exists():
                print(f"ERROR: artifacts/{rid} 不存在，拒绝追加（先跑评测或核对 run_id）",
                      file=sys.stderr)
                return 2
            if rid in DEMO_RUNS:
                print(f"skip: {rid} 已在白名单")
                continue
            added.append(rid)
        if added:
            _persist_runs(added)
            DEMO_RUNS = DEMO_RUNS + added
            print(f"白名单已追加: {', '.join(added)}（追加语义，旧 run 不动）")
        else:
            print("无新增 run，白名单不变")

    bundle = build_bundle()
    out = ROOT / "webui" / "bundle.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    out.write_text(
        "// AUTO-GENERATED by webui/build_bundle.py — do not edit.\n"
        "// window.__BUNDLE__ inlined (file:// friendly; single source: disk artifacts).\n"
        f"window.__BUNDLE__ = {payload};\n",
        encoding="utf-8",
    )
    size = out.stat().st_size
    print(f"bundle.js written: {out} ({size / 1024:.0f} KB) "
          f"runs={bundle['meta']['n_runs']} snapshots={bundle['meta']['n_snapshots']} "
          f"scenarios={bundle['meta']['n_scenarios']}")
    if size > 2 * 1024 * 1024:
        print("WARNING: bundle exceeds 2MB budget", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
