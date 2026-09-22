"""Ack CLI — on-call acknowledgement for watchdog investigations (pure record, no cluster ops).

用法：
    python -m scripts.watchdog_ack --incident-id <id> --by <name> [--note "..."]
    python -m scripts.watchdog_ack --list

语义（design D4）：
- 追加式留痕：每次 ack 追加一条到 artifacts/watchdog/ack_log.json（审计权威源，
  保留多次确认历史）；--list 取每 incident 最新一条为当前状态。
- 回写：incident_id 匹配的所有报告 JSON 回写 acknowledged_at / acknowledged_by。
- 幂等：重复 ack 不报错，只是追加新记录（历史保留）。
- 红线：纯记录动作——绝不触发任何集群操作或自动修复。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog

log = structlog.get_logger()

REPORT_DIR = Path("artifacts/watchdog")
ACK_LOG = REPORT_DIR / "ack_log.json"


def _find_reports(incident_id: str, report_dir: Path = REPORT_DIR) -> list[Path]:
    """匹配 incident_id 的报告（同 incident 可能多份，全部返回）。"""
    hits: list[Path] = []
    for p in sorted(report_dir.glob("*.json")):
        if p.name == ACK_LOG.name:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("incident_id") == incident_id:
            hits.append(p)
    return hits


def _append_ack(incident_id: str, by: str, note: str, report_paths: list[Path]) -> None:
    entry = {
        "incident_id": incident_id,
        "acknowledged_at": datetime.now(UTC).isoformat(),
        "acknowledged_by": by,
        "note": note,
        "report_paths": [str(p) for p in report_paths],
    }
    ACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if ACK_LOG.exists():
        try:
            existing = json.loads(ACK_LOG.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []
    existing.append(entry)
    ACK_LOG.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


def _rewrite_reports(report_paths: list[Path], by: str) -> None:
    now = datetime.now(UTC).isoformat()
    for p in report_paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("ack_report_rewrite_failed", path=str(p), error=repr(e)[:150])
            continue
        data["acknowledged_at"] = now
        data["acknowledged_by"] = by
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _latest_ack_by_incident(ack_log: list[dict]) -> dict[str, dict]:
    """每 incident 取最新一条（追加式日志的当前态投影）。"""
    latest: dict[str, dict] = {}
    for e in ack_log:
        latest[str(e.get("incident_id", ""))] = e
    return latest


def list_investigations(report_dir: Path = REPORT_DIR) -> list[dict]:
    """近期调查 + 确认状态（供 --list 与演示层消费）。"""
    acks: list[dict] = []
    if ACK_LOG.exists():
        try:
            acks = json.loads(ACK_LOG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            acks = []
    latest_ack = _latest_ack_by_incident(acks)

    rows: list[dict] = []
    for p in sorted(report_dir.glob("*.json"), reverse=True):
        if p.name == ACK_LOG.name:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        iid = str(data.get("incident_id", ""))
        if not iid:
            continue
        root_causes = data.get("root_causes") or [{}]
        rows.append({
            "incident_id": iid,
            "report": p.name,
            "top_service": root_causes[0].get("service", "-"),
            "top_fault_type": data.get("fault_type_classification", "-"),
            "ack": iid in latest_ack,
            "acknowledged_by": latest_ack.get(iid, {}).get("acknowledged_by", ""),
            "acknowledged_at": latest_ack.get(iid, {}).get("acknowledged_at", ""),
        })
    # 同 incident 多份报告 → 保留最新一份的行（文件名时间戳排序已保证）
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in rows:
        if r["incident_id"] in seen:
            continue
        seen.add(r["incident_id"])
        deduped.append(r)
    return deduped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watchdog-ack",
        description="值守确认：对 watchdog 调查留 ack 记录（纯记录，不触发任何集群操作）",
    )
    parser.add_argument("--incident-id", default="", help="incident to acknowledge")
    parser.add_argument("--by", default="", help="who acknowledges (required with --incident-id)")
    parser.add_argument("--note", default="", help="optional note")
    parser.add_argument("--list", action="store_true",
                        help="list recent investigations + ack state")
    args = parser.parse_args(argv)

    if args.list:
        rows = list_investigations()
        if not rows:
            print("（无调查记录）")
            return 0
        print(f"{'INCIDENT_ID':44s} {'TOP-1':28s} {'ACK':5s} {'BY':10s}")
        for r in rows:
            top = f"{r['top_service']}/{r['top_fault_type']}"
            print(f"{r['incident_id']:44s} {top:28s} "
                  f"{'✅' if r['ack'] else '⬜':5s} {r['acknowledged_by']:10s}")
        n_acked = sum(1 for r in rows if r["ack"])
        print(f"\n共 {len(rows)} 个 incident，已确认 {n_acked}，未确认 {len(rows) - n_acked}")
        return 0

    if not args.incident_id or not args.by:
        parser.error("--incident-id 与 --by 必填（或使用 --list）")

    reports = _find_reports(args.incident_id)
    if not reports:
        print(f"未找到 incident_id={args.incident_id} 的报告（查 artifacts/watchdog/）")
        return 1

    _append_ack(args.incident_id, args.by, args.note, reports)
    _rewrite_reports(reports, args.by)
    log.info("ack_recorded", incident_id=args.incident_id, by=args.by, n_reports=len(reports))
    print(f"已确认 {args.incident_id}（by {args.by}）：ack_log 追加 1 条，"
          f"回写 {len(reports)} 份报告")
    return 0


if __name__ == "__main__":
    sys.exit(main())
