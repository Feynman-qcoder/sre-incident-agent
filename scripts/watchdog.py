"""CLI entry for the alert watchdog (只做参数转发，风格对齐 src/agent/run.py).

用法：
    python -m scripts.watchdog --once                       # 单轮轮询后退出
    python -m scripts.watchdog --interval 15                # 值班长驻模式
    python -m scripts.watchdog --dry-run --once             # 零成本演练（不调 LLM、不落报告）
    python -m scripts.watchdog --dry-run --once \\
        --alerts-file tests/fixtures/alerts_live_20260916.json   # 离线对 fixture 演练
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import structlog
from dotenv import load_dotenv

load_dotenv()  # PROMETHEUS_URL / TEMPO_URL / LOKI_URL 与 LiveDataSource 同源

log = structlog.get_logger()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="watchdog",
        description="告警驱动的值班调查 Agent：轮询 Prometheus 告警，"
                    "过滤噪声后自动发起 live 调查（只诊断、不修复）",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true",
                      help="run a single polling cycle then exit")
    mode.add_argument("--interval", type=int, default=30, metavar="N",
                      help="polling interval in seconds for watch mode (default: 30)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be investigated; no LLM calls, no report files")
    parser.add_argument("--max-investigations-per-hour", type=int, default=6,
                        help="hourly budget for automatic investigations (default: 6)")
    parser.add_argument("--cooldown-min", type=int, default=45,
                        help="per-fingerprint cooldown in minutes (default: 45)")
    parser.add_argument("--service-cooldown-min", type=int, default=45,
                        help="per-service aggregate cooldown in minutes: any whitelisted "
                             "alert of a service already investigated within this window "
                             "is skipped (0 disables aggregation, default: 45)")
    parser.add_argument("--prometheus-url", default=None,
                        help="default: $PROMETHEUS_URL or http://localhost:9090")
    parser.add_argument("--alerts-file", default=None,
                        help="offline mode: read alerts from a captured JSON file "
                             "instead of HTTP (for unit tests / dry-run drills)")
    parser.add_argument("--replay-alerts", default=None, metavar="FILE",
                        help="G-4 offline demo: replay a recorded alert stream (jsonl, "
                             "one alerts-array per line) through the full pipeline "
                             "(filter/dedup/cooldown/investigate), then exit. "
                             "The stream is a real recorded subset — never fabricated.")
    notify_group = parser.add_mutually_exclusive_group()
    notify_group.add_argument("--notify", action="store_true", default=True,
                              help="send WeCom notification after each investigation "
                                   "(default: on; uses $WECOM_WEBHOOK_URL)")
    notify_group.add_argument("--no-notify", action="store_true",
                              help="disable WeCom notifications (investigation only)")
    parser.add_argument("--notify-webhook", default=None,
                        help="override $WECOM_WEBHOOK_URL for this run "
                             "(credential — never logged in full)")
    return parser.parse_args(argv)


def _load_alerts_from_file(path: str) -> list[dict[str, object]]:
    """Accept either a raw /api/v1/alerts response or a bare alerts list."""
    data: object = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("data", {}).get("alerts", [])  # type: ignore[return-value]
    if isinstance(data, list):
        return data  # type: ignore[return-value]
    raise ValueError(f"unrecognized alerts file structure: {path}")


def _replay(args: argparse.Namespace, alerter: object,
            run_investigation_fn: object, check_backends_fn: object) -> int:
    """G-4：回放真实录制的告警流（每行一个轮次的 alerts 数组）。"""
    path = Path(args.replay_alerts)
    n_cycles = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        ln = line.strip()
        if not ln or ln.startswith("#"):
            continue  # 文件头注释（来源声明）与空行
        alerts = json.loads(ln)
        n_cycles += 1
        log.info("replay_cycle", cycle=n_cycles, n_alerts=len(alerts))
        passed = alerter.process(alerts)  # type: ignore[attr-defined]
        for item in passed:
            if args.dry_run:
                run_investigation_fn(item, dry_run=True)  # type: ignore[call-arg]
                continue
            if not check_backends_fn():
                log.warning("replay_backend_not_ready", skip=True)
                continue
            alerter.mark_investigated(item)  # type: ignore[attr-defined]
            run_investigation_fn(  # type: ignore[call-arg]
                item,
                notify=not args.no_notify,
                notify_webhook=args.notify_webhook,
            )
    log.info("replay_complete", cycles=n_cycles, path=str(path))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from src.watchdog.alerter import Alerter
    from src.watchdog.runner import check_backends, run_investigation

    alerter = Alerter(
        prometheus_url=args.prometheus_url,
        cooldown_min=args.cooldown_min,
        max_per_hour=args.max_investigations_per_hour,
        service_cooldown_min=args.service_cooldown_min,
    )

    # ── G-4 离线回放模式（add-local-demo-pack）：jsonl 逐行 = 一个轮次的告警数组，
    #    按序走 process() 全链（过滤/去重/冷却复用同一代码路径），回放完退出。
    if args.replay_alerts:
        return _replay(args, alerter, run_investigation, check_backends)

    while True:
        # ── 1. 拉取告警（HTTP 或离线 fixture 文件）────────────────────────────
        try:
            if args.alerts_file:
                alerts = _load_alerts_from_file(args.alerts_file)
            else:
                alerts = alerter.fetch_alerts()
        except Exception as e:  # noqa: BLE001 — keep the loop alive, retry next cycle
            log.error("fetch_alerts_failed", error=repr(e)[:300])
            if args.once:
                return 1
            time.sleep(max(args.interval, 5))
            continue

        # ── 2. 过滤 + 去重 + 冷却 + 小时限额（alerter 内打 3 类日志事件）─────
        passed = alerter.process(alerts)

        # ── 3. 串行执行调查（同一时刻仅 1 个；忙时本轮自然排队到下轮）────────
        for item in passed:
            if args.dry_run:
                run_investigation(item, dry_run=True)  # 只打 would_start 日志
                continue
            if not check_backends():
                # 不写指纹：告警仍 firing，下一轮自然重试（≤3 次探测在函数内完成）
                log.warning("backend_not_ready_skip_cycle",
                            fingerprint=item["fingerprint"], alertname=item["alertname"])
                continue
            alerter.mark_investigated(item)  # 调查开始即占指纹，防调查期间重复触发
            run_investigation(
                item,
                notify=not args.no_notify,
                notify_webhook=args.notify_webhook,
            )

        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
