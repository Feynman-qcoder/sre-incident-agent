"""Orchestrate auto-investigations — the ONLY module touching existing agent interfaces.

职责（design.md D2/D5/D6）：
- 触发前三后端健康检查（Prometheus ``/-/healthy``、Tempo/Loki ``/ready``），
  任一失败 → 原地延后重试 ≤3 次，全失败则本轮不调查、不产报告；
- 复用既有调查链路（与 src/agent/run.py 完全一致的调用方式）：
  ``LiveDataSource() → build_graph(ds) → initial_state(...) → graph.invoke``；
- 报告落盘 ``artifacts/watchdog/<UTC时间戳>_<alertname>_<service>.json``
  （InvestigationReport.model_dump_json，与评测产物同构）；
- 单次调查超时 ≤10 min、失败重试 ≤2 次（共 ≤3 次尝试）；调查在 daemon 线程
  中执行，超时不阻塞主轮询循环。

延迟导入约定：``_invoke_graph`` / ``run_investigation`` 内部才 import 既有 agent
模块 —— dry-run 与单测路径 import 本模块时零 LLM、零 K8s 客户端依赖。

日志事件（本模块负责 2/5 类）：
- ``investigation_started``   含 incident_id 与窗口
- ``investigation_complete``  含 top 服务/故障类型/延迟/成本
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

INVESTIGATION_TIMEOUT_S = 600.0  # 单次调查超时 ≤10 min（spec）
MAX_INVESTIGATION_RETRIES = 2    # 失败重试 ≤2 次（spec；共 ≤3 次尝试）

# 与 scripts/health_check.py 同约定的就绪端点
HEALTH_ENDPOINTS: dict[str, str] = {
    "prometheus": "/-/healthy",
    "tempo": "/ready",
    "loki": "/ready",
}


def _backend_urls() -> dict[str, str]:
    """LiveDataSource 直读同一组环境变量，此处保持一致、不硬编码端口。"""
    return {
        "prometheus": os.getenv("PROMETHEUS_URL", "http://localhost:9090").rstrip("/"),
        "tempo": os.getenv("TEMPO_URL", "http://localhost:3200").rstrip("/"),
        "loki": os.getenv("LOKI_URL", "http://localhost:3100").rstrip("/"),
    }


def check_backends(retries: int = 3, delay_s: float = 10.0) -> bool:
    """Probe Prometheus/Tempo/Loki readiness; retry ≤3 with delay. True iff all ready."""
    urls = _backend_urls()
    for attempt in range(1, retries + 1):
        results: dict[str, bool] = {}
        for name, base in urls.items():
            try:
                r = httpx.get(f"{base}{HEALTH_ENDPOINTS[name]}", timeout=5.0)
                results[name] = r.status_code == 200
            except httpx.HTTPError:
                results[name] = False
        if all(results.values()):
            return True
        log.warning("backends_not_ready", attempt=attempt, results=results)
        if attempt < retries:
            time.sleep(delay_s)
    return False


def _run_with_timeout(func: Callable[[], Any], timeout_s: float) -> Any:
    """Run func() in a daemon thread; raise TimeoutError past the deadline."""
    box: dict[str, Any] = {}
    done = threading.Event()

    def _target() -> None:
        try:
            box["result"] = func()
        except BaseException as e:  # noqa: B036 — re-raised in caller thread below
            box["error"] = e
        finally:
            done.set()

    t = threading.Thread(target=_target, daemon=True, name="watchdog-investigation")
    t.start()
    if not done.wait(timeout_s):
        raise TimeoutError(f"investigation exceeded {timeout_s}s")
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _invoke_graph(state: dict[str, object],
                  audit_path: str | Path | None = None) -> dict[str, object]:
    """Delayed import: dry-run/unit-test paths never touch LLM / K8s clients."""
    from src.agent.graph import build_graph
    from src.datasources.live import LiveDataSource

    ds = LiveDataSource()
    # add-tool-gateway：审计与报告同目录（audit_path 由 run_investigation 传入）
    graph = build_graph(ds, audit_path=audit_path)
    return graph.invoke(state)  # type: ignore[return-value]


def run_investigation(
    item: dict[str, object],
    report_dir: str | Path = "artifacts/watchdog",
    dry_run: bool = False,
    timeout_s: float = INVESTIGATION_TIMEOUT_S,
    max_retries: int = MAX_INVESTIGATION_RETRIES,
    notify: bool = True,
    notify_webhook: str | None = None,
) -> Path | None:
    """Execute one investigation for a passed alert item (from Alerter.process).

    Returns the report path on success, None on permanent failure / dry-run.
    ``notify``（add-oncall-loop）：investigation_complete 后推送企微诊断摘要
    （降级设计——通知失败仅记 notification_failed，主流程零影响）。
    """
    alertname = str(item["alertname"])
    service = str(item["service_hint"])
    fingerprint = str(item["fingerprint"])
    incident_id = f"watchdog-{alertname}-{fingerprint}"  # 便于从报告反查触发告警
    window_start = str(item["window_start"])
    window_end = str(item["window_end"])

    if dry_run:
        log.info(
            "investigation_would_start",
            incident_id=incident_id,
            alertname=alertname,
            service=service,
            fault_type_hint=item["fault_type_hint"],
            window_start=window_start,
            window_end=window_end,
        )
        return None

    # add-incident-memory：检索键 = 告警映射的 service_hint + fault_type_hint
    #（INCIDENT_MEMORY=off 时返回空串，行为与变更前一致）
    from src.agent.memory import maybe_retrieve_and_build
    from src.agent.schemas import initial_state  # 调查路径内延迟导入（纯 schema，无 LLM）
    hint_block, _hit = maybe_retrieve_and_build(service, str(item["fault_type_hint"]))

    state = initial_state(
        incident_id=incident_id,
        incident_start_ts=window_start,
        incident_end_ts=window_end,
        affected_namespace=str(item["namespace"]),
        memory_hint=hint_block,
    )
    state["_investigation_start_ts"] = datetime.now(UTC).isoformat()

    log.info(
        "investigation_started",
        incident_id=incident_id,
        alertname=alertname,
        service=service,
        fault_type_hint=item["fault_type_hint"],
        window_start=window_start,
        window_end=window_end,
    )
    started = time.monotonic()

    report = None
    # add-tool-gateway：审计文件与报告同目录，incident_id 命名配对（先建目录）
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_path = out_dir / f"tool_audit_{incident_id}.jsonl"

    for attempt in range(1, max_retries + 2):
        try:
            result = _run_with_timeout(
                lambda: _invoke_graph(state, audit_path=audit_path), timeout_s)
            report = result.get("final_report") if isinstance(result, dict) else None
            if report is None:
                raise RuntimeError("graph produced no final_report")
            break
        except Exception as e:  # noqa: BLE001 — any failure: log and maybe retry
            log.warning(
                "investigation_attempt_failed",
                incident_id=incident_id,
                attempt=attempt,
                max_attempts=max_retries + 1,
                error=repr(e)[:300],
            )
            if attempt > max_retries:
                log.error("investigation_failed_permanently", incident_id=incident_id)
                return None

    if report is None:  # unreachable (loop returns on final failure); defensive
        log.error("investigation_failed_permanently", incident_id=incident_id)
        return None

    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{ts}_{alertname}_{service}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    log.info(
        "investigation_complete",
        incident_id=incident_id,
        report_path=str(path),
        top_service=report.root_causes[0].service if report.root_causes else "none",
        top_fault_type=report.fault_type_classification,
        latency_s=report.latency_s,
        cost_usd=report.cost_usd,
        wall_latency_s=round(time.monotonic() - started, 1),
    )

    # ── add-oncall-loop D3：诊断摘要出站通知（增强，非依赖）──────────────────
    # 三事件：notification_sent / notification_failed / notification_disabled
    # （notifier 内打）；此处再包一层 try/except 兜底——通知链路任何异常都
    # 不改变 run_investigation 的返回值（报告已落盘，调查已完成）。
    if notify:
        try:
            from src.watchdog.notifier import notify_investigation
            notify_investigation(
                report, path,
                alertname=alertname, service=service,
                incident_id=incident_id, webhook_url=notify_webhook,
            )
        except Exception as e:  # noqa: BLE001 — 双保险：notifier 自身 bug 也不影响主流程
            log.warning("notification_failed", incident_id=incident_id, error=repr(e)[:200])
    else:
        log.info("notification_disabled", incident_id=incident_id, reason="--no-notify")

    # ── add-incident-memory：writer（调查完成后记录；失败仅告警不影响主流程）──
    try:
        from src.agent.memory import memory_enabled, write_incident
        if memory_enabled():
            report._memory_service = service
            report._memory_fault_type = str(item["fault_type_hint"])
            write_incident(report, path)
    except Exception as e:  # noqa: BLE001 — 记忆写入永不影响调查主流程
        log.warning("memory_write_gate_failed", incident_id=incident_id, error=repr(e)[:150])

    return path
