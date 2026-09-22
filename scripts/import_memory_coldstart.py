"""Cold-start import — historical investigation reports → memory/incidents/.

add-incident-memory D6（一次性脚本 + 人工 review）：
- 扫四个报告来源（P0 E2E / glm run / deepseek run / oncall 真实事故 / eval replay）；
- 按 scenario_id 去重：同 scenario 的 glm/deepseek/eval 多版本只保留最新（deepseek
  优先于 glm，按报告时间戳），真实事故报告（watchdog-* incident）全部保留；
- 生成 memory/incidents/*.md + INDEX.md（git diff 供人工 review 后再提交）。

用法：
    python -m scripts.import_memory_coldstart            # 全量导入
    python -m scripts.import_memory_coldstart --rebuild-index   # 仅重建 INDEX
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.memory import INCIDENTS_DIR, rebuild_index  # noqa: E402

# 来源目录（相对仓库根）：扫描其中的 *.json 调查报告
SOURCES = [
    "artifacts/watchdog-e2e-cloud",                  # P0 E2E（3 份，20260916T13*）
    "artifacts/watchdog-golden-e2e-cloud",           # glm run（15 份）
    "artifacts/watchdog-golden-e2e-cloud-deepseek",  # deepseek run（19 份）
    "artifacts/oncall-e2e-cloud",                    # oncall 真实事故（6 份）
    "artifacts/20260917T152725Z",                    # eval replay（7 份）
]


def _iter_reports() -> list[Path]:
    out: list[Path] = []
    for src in SOURCES:
        d = Path(src)
        if not d.exists():
            continue
        # 三种布局：根 *.json（oncall/平铺）、reports/*.json（E2E 打包子目录）、
        # scenarios/<id>/report.json（eval run）
        out.extend(p for p in sorted(d.glob("*.json")) if p.name != "state.json")
        out.extend(p for p in sorted(d.glob("reports/*.json")) if p.name != "state.json")
        out.extend(p for p in sorted(d.glob("scenarios/*/report.json")))
    return [p for p in out if _looks_like_report(p)]


def _looks_like_report(p: Path) -> bool:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and "incident_id" in data and "root_causes" in data


def _report_key(data: dict) -> tuple[str, str]:
    """去重键：(kind, id)。eval 报告按 scenario_id 聚合；watchdog 按 incident_id。"""
    iid = str(data.get("incident_id", ""))
    if iid.startswith("watchdog-"):
        return ("watchdog", iid)
    return ("scenario", iid)  # eval replay：incident_id == scenario_id


def _write_md(data: dict, source: Path, stats: dict[str, int]) -> None:
    iid = str(data["incident_id"])
    root = (data.get("root_causes") or [{}])[0]
    # 触发键：watchdog 从 incident_id 反解告警名；eval 场景从 scenario_id 反解
    m = re.match(r"watchdog-(.+?)-[0-9a-f]{8}$", iid)
    if m:
        svc = str(data.get("_trigger_service") or root.get("service", "unknown"))
        fault_hint = {"KubePodCrashLooping": "pod_crash", "KubePodNotReady": "pod_crash",
                      "KubeDeploymentReplicasMismatch": "pod_crash",
                      "KubeStatefulSetReplicasMismatch": "pod_crash",
                      "OtelDemoHighLatencyP99": "high_latency",
                      "OtelDemoHighErrorRate": "http_abort"}.get(m.group(1), "unknown")
        # 触发服务：报告的 top-1 不一定是触发服务——导入时以 root_cause 服务作为
        # service 键（记忆的检索价值在"根因关联"：同服务同故障类型的历史根因）
        svc = str(root.get("service", svc))
    else:
        # eval 场景：<service>-<fault>-seed42 → service/fault 可靠反解
        m2 = re.match(r"(.+?)-(pod_crash|high_latency|cpu_stress|memory_stress|http_abort)-seed",
                      iid)
        if m2:
            svc, fault_hint = m2.group(1), m2.group(2)
        else:
            svc = str(root.get("service", "unknown"))
            fault_hint = str(data.get("fault_type_classification", "unknown"))

    created = str(data.get("investigation_end_ts") or data.get("investigation_start_ts") or "")
    desc = str(root.get("description") or "")
    summary = desc.splitlines()[0] if desc else "（无）"
    lines = [
        "---",
        f"incident_id: {iid}",
        f"service: {svc}",
        f"fault_type: {fault_hint}",
        f"root_cause_service: {root.get('service', 'unknown')}",
        f"root_cause_fault_type: {data.get('fault_type_classification', 'unknown')}",
        f"confidence: {float(root.get('confidence', 0)):.2f}",
        f"created_at: {created}",
        f"source_report: {source.as_posix()}",
        "---", "",
        f"# {iid}", "",
        f"**根因摘要**：{summary}",
        "",
        "**修复建议**：",
    ]
    steps = (data.get("remediation_steps") or [])[:5]
    lines += [f"- {s}" for s in steps] or ["- （无）"]
    lines += ["", "**证据要点**："]
    ev = [str(getattr(e, "summary", e) if not isinstance(e, dict) else e.get("summary", e))
          for e in (root.get("evidence") or [])][:5]
    lines += [f"- {str(e)[:120]}" for e in ev] or ["- （略，见 source_report）"]
    lines.append("")

    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", iid)
    (INCIDENTS_DIR / f"{safe}.md").write_text("\n".join(lines), encoding="utf-8")
    stats["written"] += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cold-start incident memory import")
    parser.add_argument("--rebuild-index", action="store_true",
                        help="only rebuild INDEX.md from existing incidents/")
    args = parser.parse_args(argv)

    if args.rebuild_index:
        n = rebuild_index()
        print(f"INDEX rebuilt: {n} entries")
        return 0

    reports = _iter_reports()
    stats = {"scanned": len(reports), "deduped": 0, "written": 0, "superseded": 0}
    by_source: dict[str, int] = {}
    # 同 key 保留最新（investigation_end_ts 比较；deepseek 晚于 glm 天然胜出）
    best: dict[tuple[str, str], tuple[str, Path, dict]] = {}
    for p in reports:
        data = json.loads(p.read_text(encoding="utf-8"))
        key = _report_key(data)
        ts = str(data.get("investigation_end_ts", ""))
        src_label = p.parts[1] if len(p.parts) > 1 else str(p)
        by_source[src_label] = by_source.get(src_label, 0) + 1
        if key in best:
            stats["superseded"] += 1
            if ts > best[key][0]:
                best[key] = (ts, p, data)
        else:
            best[key] = (ts, p, data)

    stats["deduped"] = len(best)
    for _ts, p, data in best.values():
        _write_md(data, p, stats)
    rebuild_index()

    print(f"scanned: {stats['scanned']} reports across {len(by_source)} sources")
    for src, n in sorted(by_source.items()):
        print(f"  {src}: {n}")
    print(f"dedup: superseded {stats['superseded']} → kept {stats['deduped']} unique incidents")
    print(f"written: {stats['written']} files to memory/incidents/ + INDEX")
    return 0


if __name__ == "__main__":
    sys.exit(main())
