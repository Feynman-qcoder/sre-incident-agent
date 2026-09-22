"""Incident memory — file-based long-term memory for investigations (V1).

add-incident-memory design D1-D4：
- 三层结构：INDEX.md（派生索引）/ incidents/<incident_id>.md（AI 记录）/
  notes/lessons.md（人工经验层，命中优先）；
- 检索：service + fault_type 精确匹配（结构化键优于向量——用户拍板），
  created_at 降序 top-k；notes 条目优先且标注来源；
- Hint ≠ Evidence：本模块产物只进独立 Hint 消息，与 tool_calls_log 零交集
  （grounding 校验天然不含记忆）；Hint 块首行免责声明；
- 开关：INCIDENT_MEMORY=off → 全部入口不检索不写入（行为与变更前一致）。

零第三方依赖（frontmatter 手动解析：键: 值 平面结构足够，无需 pyyaml）。
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path

import structlog

log = structlog.get_logger()

MEMORY_DIR = Path(os.getenv("INCIDENT_MEMORY_DIR", "memory"))
INCIDENTS_DIR = MEMORY_DIR / "incidents"
NOTES_PATH = MEMORY_DIR / "notes" / "lessons.md"
INDEX_PATH = MEMORY_DIR / "INDEX.md"

TOP_K_DEFAULT = 3
MAX_LINES_PER_RECORD = 15
DISCLAIMER = (
    "以下为历史调查参考，非当前证据；最终根因结论必须由当前工具调用证据支撑。"
)

# frontmatter 平面键（write 顺序即文件内顺序）
_FM_KEYS = [
    "incident_id", "service", "fault_type",
    "root_cause_service", "root_cause_fault_type",
    "confidence", "created_at", "source_report",
]


def memory_enabled() -> bool:
    return os.getenv("INCIDENT_MEMORY", "on").strip().lower() != "off"


# ── writer ──────────────────────────────────────────────────────────────────

def write_incident(report: object, report_path: str | Path) -> Path | None:
    """调查完成后把 InvestigationReport 追加为 incidents/<incident_id>.md。

    - 同 incident_id 再写 = 覆盖更新（最新调查覆盖旧记录，幂等）；
    - 同时更新 INDEX.md；失败仅告警（不影响调查主流程），返回 None。
    """
    try:
        iid = str(getattr(report, "incident_id", "") or "")
        if not iid:
            log.warning("memory_write_skipped", reason="no incident_id")
            return None
        root = report.root_causes[0] if report.root_causes else None  # type: ignore[attr-defined]
        frontmatter = {
            "incident_id": iid,
            "service": "",  # 触发服务（watchdog 告警映射）；replay 时 = 场景服务
            "fault_type": "",
            "root_cause_service": root.service if root else "unknown",
            "root_cause_fault_type": str(getattr(report, "fault_type_classification", "unknown")),
            "confidence": f"{float(root.confidence):.2f}" if root else "0.00",
            "created_at": datetime.now(UTC).isoformat(),
            "source_report": str(report_path),
        }
        # 触发键（service/fault_type）从报告上下文补：watchdog 传 hint，见调用方
        svc = getattr(report, "_memory_service", None) or frontmatter["root_cause_service"]
        ft = getattr(report, "_memory_fault_type", None) or frontmatter["root_cause_fault_type"]
        frontmatter["service"] = str(svc)
        frontmatter["fault_type"] = str(ft)

        summary = (root.description if root else "（无根因假设）").split("\n")[0]
        steps = list(getattr(report, "remediation_steps", []) or [])[:5]
        evidence = [str(getattr(e, "summary", e))[:120]
                    for e in (getattr(root, "evidence", None) or [])][:5]

        lines = ["---"]
        for k in _FM_KEYS:
            lines.append(f"{k}: {frontmatter[k]}")
        lines += ["---", "", f"# {iid}", "",
                  f"**根因摘要**：{summary}", "",
                  "**修复建议**："]
        lines += [f"- {s}" for s in steps] or ["- （无）"]
        lines += ["", "**证据要点**："]
        lines += [f"- {e}" for e in evidence] or ["- （略，见 source_report）"]
        lines.append("")

        INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
        safe_iid = re.sub(r"[^A-Za-z0-9._-]", "_", iid)
        path = INCIDENTS_DIR / f"{safe_iid}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        rebuild_index()
        log.info("memory_written", incident_id=iid, path=str(path))
        return path
    except Exception as e:  # noqa: BLE001 — writer 失败仅告警，不影响调查主流程
        log.warning("memory_write_failed", error=repr(e)[:200])
        return None


# ── index（派生物：可从 incidents/ 全量重建）───────────────────────────────

def _parse_frontmatter(path: Path) -> dict[str, str]:
    fm: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return fm
    if not text.startswith("---"):
        return fm
    for line in text.split("---", 2)[1].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def rebuild_index() -> int:
    """从 incidents/ 全量重建 INDEX.md；返回条目数。"""
    entries: list[tuple[str, str, str, str]] = []  # (service, fault_type, iid, file)
    if INCIDENTS_DIR.exists():
        for p in sorted(INCIDENTS_DIR.glob("*.md")):
            fm = _parse_frontmatter(p)
            if fm.get("incident_id"):
                entries.append((fm.get("service", ""), fm.get("fault_type", ""),
                                fm["incident_id"], p.name))
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# INDEX — incident memory routing (derived, rebuildable)",
        "",
        "每行：service | fault_type → incident 文件。派生物：与 incidents/ 不一致时以文件为准",
        "（`python -m scripts.import_memory_coldstart --rebuild-index` 重建）。",
        "",
        "| service | fault_type | incident | file |",
        "|---|---|---|---|",
    ]
    for svc, ft, iid, fname in entries:
        lines.append(f"| {svc} | {ft} | {iid} | incidents/{fname} |")
    INDEX_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(entries)


# ── retrieval ────────────────────────────────────────────────────────────────

def _match_notes(service: str, fault_type: str) -> list[dict[str, str]]:
    """notes/lessons.md 人工条目：行内 `service:`/`fault_type:` 标记命中。"""
    hits: list[dict[str, str]] = []
    if not NOTES_PATH.exists():
        return hits
    try:
        text = NOTES_PATH.read_text(encoding="utf-8")
    except OSError:
        return hits
    for block in re.split(r"\n## ", text)[1:]:
        if f"service: {service}" in block and f"fault_type: {fault_type}" in block:
            hits.append({
                "source": "notes", "service": service, "fault_type": fault_type,
                "created_at": "", "body": f"## {block}".strip()[:2000],
            })
    return hits


def retrieve(service: str, fault_type: str, top_k: int = TOP_K_DEFAULT) -> list[dict[str, str]]:
    """service + fault_type 精确匹配 → notes 优先 + incidents created_at 降序 top-k。"""
    records: list[dict[str, str]] = []
    for n in _match_notes(service, fault_type):
        records.append(n)
    if INCIDENTS_DIR.exists():
        for p in sorted(INCIDENTS_DIR.glob("*.md")):
            fm = _parse_frontmatter(p)
            if fm.get("service") == service and fm.get("fault_type") == fault_type:
                records.append({
                    "source": "incidents", "service": service, "fault_type": fault_type,
                    "created_at": fm.get("created_at", ""),
                    "body": p.read_text(encoding="utf-8")[:2000],
                    "root_cause_service": fm.get("root_cause_service", ""),
                    "root_cause_fault_type": fm.get("root_cause_fault_type", ""),
                    "confidence": fm.get("confidence", ""),
                    "incident_id": fm.get("incident_id", p.stem),
                })
    # notes 在前（人工优先）；incidents 组内 created_at 降序；总量 top_k
    notes = [r for r in records if r["source"] == "notes"]
    incs = sorted((r for r in records if r["source"] == "incidents"),
                  key=lambda r: r["created_at"], reverse=True)
    return (notes + incs)[:top_k]


# ── hint block ───────────────────────────────────────────────────────────────

def build_hint_block(records: list[dict[str, str]]) -> str:
    """构造注入 Agent 的独立 Hint 块（首行免责声明；每条 ≤ MAX_LINES_PER_RECORD 行）。"""
    if not records:
        return ""
    lines = [f"[INCIDENT MEMORY — {DISCLAIMER}]"]
    for i, r in enumerate(records, 1):
        body_lines = [ln for ln in r["body"].splitlines() if ln.strip()]
        if r["source"] == "incidents":
            rcs = r.get("root_cause_service", "?")
            rcf = r.get("root_cause_fault_type", "?")
            head = (f"历史 #{i}（{r['created_at'][:10]}，{r['service']}/{r['fault_type']}，"
                    f"根因 {rcs}/{rcf}，置信度 {r.get('confidence', '?')}）")
        else:
            head = f"人工经验 #{i}（notes/lessons.md，{r['service']}/{r['fault_type']}）"
        lines.append(head)
        lines.extend(body_lines[:MAX_LINES_PER_RECORD])
    lines.append("[/INCIDENT MEMORY]")
    return "\n".join(lines)


def maybe_retrieve_and_build(service: str, fault_type: str) -> tuple[str, bool]:
    """挂点便捷入口：返回 (hint_block, hit)。开关 off → ('', False) 且零文件 IO。"""
    if not memory_enabled():
        return "", False
    records = retrieve(service, fault_type)
    if not records:
        log.info("memory_miss", service=service, fault_type=fault_type)
        return "", False
    log.info("memory_hit", service=service, fault_type=fault_type, n_records=len(records))
    return build_hint_block(records), True
