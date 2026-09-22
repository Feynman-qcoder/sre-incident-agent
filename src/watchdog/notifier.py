"""WeCom group-bot notifier — investigation summary to the on-call group.

职责（add-oncall-loop design D3，单一职责模块）：
- ``build_markdown(...)``   构造企微 markdown 消息（纯函数，易单测）；
- ``send_markdown(...)``    POST 群机器人 webhook（timeout 10s，企微 payload 格式）；
- ``notify_investigation(...)``  组合入口：读报告 → 构造 → 发送 → 打结构化事件。

降级设计（沿 P0"后端不可达跳过本轮"哲学）：
- webhook 未配置 → ``notification_disabled`` 事件，直接返回（不报错）；
- 发送失败 → ``notification_failed`` 事件（含错误摘要），**不抛出**——通知是增强，
  不是依赖；调用方（runner）另有一层 try/except 兜底，核心链路永不中断。
- 日志脱敏：webhook 只打 host（``qyapi.weixin.qq.com``），绝不打完整 URL（URL 即凭据）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
import structlog

log = structlog.get_logger()

MAX_REMEDIATION_STEPS = 3          # 消息里只送前 3 条修复建议（spec MUST）
WECOM_TIMEOUT_S = 10.0             # POST 超时（spec）


def build_markdown(
    incident_id: str,
    alertname: str,
    service: str,
    top_service: str,
    top_fault_type: str,
    top_confidence: float,
    root_cause_summary: str,
    remediation_steps: list[str],
    report_path: str,
) -> str:
    """构造企微 markdown 文本（字段集 = spec Requirement 2 的 MUST 集合）。"""
    lines = [
        "## 🔍 Watchdog 自动诊断完成",
        f"**告警**：`{alertname}` @ `{service}`",
        f"**Incident**：`{incident_id}`",
        "",
        f"**Top-1 根因**：`{top_service}` / `{top_fault_type}`（置信度 {top_confidence:.0%}）",
        f"**摘要**：{root_cause_summary}",
        "",
        "**修复建议**：",
    ]
    steps = remediation_steps[:MAX_REMEDIATION_STEPS]
    if not steps:
        lines.append("（报告未产出修复建议）")
    for i, step in enumerate(steps, 1):
        lines.append(f"{i}. {step}")
    lines += [
        "",
        f"**报告**：`{report_path}`",
        "",
        "**确认值守**：`python -m scripts.watchdog_ack --incident-id "
        f"{incident_id} --by <你的名字>`",
    ]
    return "\n".join(lines)


def send_markdown(webhook_url: str, markdown: str, timeout_s: float = WECOM_TIMEOUT_S) -> None:
    """POST 企微群机器人 markdown 消息；失败抛 httpx 异常（由上层降级）。"""
    payload = {"msgtype": "markdown", "markdown": {"content": markdown}}
    resp = httpx.post(webhook_url, json=payload, timeout=timeout_s)
    resp.raise_for_status()
    # 企微返回 200 + {"errcode":0,...}；非 0 errcode 视为失败
    body = resp.json()
    if body.get("errcode") != 0:
        raise RuntimeError(f"wecom api errcode={body.get('errcode')} errmsg={body.get('errmsg')}")


def _webhook_host(url: str) -> str:
    return urlparse(url).netloc or "unknown"


def notify_investigation(
    report: object,
    report_path: str | Path,
    alertname: str,
    service: str,
    incident_id: str = "",
    webhook_url: str | None = None,
) -> bool:
    """investigation_complete 后的出站通知入口（runner 挂载点）。

    - webhook 优先级：显式参数 > $WECOM_WEBHOOK_URL；都空 → notification_disabled。
    - 报告对象须为 InvestigationReport（有 root_causes / remediation_steps）。
    - 返回 True=已发送；False=跳过或失败（均不抛出）。
    """
    url = webhook_url or os.getenv("WECOM_WEBHOOK_URL", "")
    iid = incident_id or str(getattr(report, "incident_id", ""))
    if not url:
        log.info("notification_disabled", incident_id=iid, reason="WECOM_WEBHOOK_URL not set")
        return False

    top = report.root_causes[0] if report.root_causes else None  # type: ignore[attr-defined]
    top_service = top.service if top else "unknown"
    top_fault_type = str(getattr(report, "fault_type_classification", "unknown"))
    top_confidence = float(top.confidence) if top else 0.0
    summary = (top.description if top else "（无根因假设）").split("\n")[0]
    steps = list(getattr(report, "remediation_steps", []) or [])

    md = build_markdown(
        incident_id=iid,
        alertname=alertname,
        service=service,
        top_service=top_service,
        top_fault_type=top_fault_type,
        top_confidence=top_confidence,
        root_cause_summary=summary,
        remediation_steps=steps,
        report_path=str(report_path),
    )
    try:
        send_markdown(url, md)
    except Exception as e:  # noqa: BLE001 — 降级：只记事件，绝不影响调查主流程
        log.warning("notification_failed", incident_id=iid,
                    webhook_host=_webhook_host(url), error=repr(e)[:200])
        return False
    log.info("notification_sent", incident_id=iid, webhook_host=_webhook_host(url))
    return True


def load_report(report_path: str | Path) -> dict[str, object]:
    """读报告 JSON（ack CLI 复用：--list 展示与回写）。"""
    return json.loads(Path(report_path).read_text(encoding="utf-8"))
