"""Poll Prometheus /api/v1/alerts; whitelist-filter, fingerprint-dedup, cooldown.

设计要点（design.md D1/D3）：
- fetch_alerts() 是本模块唯一的网络 IO；process() 是纯状态机（传入 alerts
  列表与 now），单测无需网络、无需 LLM。
- 去重状态 JSON 落盘（artifacts/watchdog/state.json），进程重启不丢冷却；
  加载失败 → 告警并重建空表（最坏代价是多跑一次调查）。

日志事件（本模块负责 4 类）：
- ``alert_seen``         白名单内的新告警通过过滤
- ``alert_filtered``     被过滤（reason: not_in_whitelist / wrong_namespace /
                         hourly_limit_exceeded）
- ``skipped_cooldown``   冷却期内重复告警被丢弃（含指纹与剩余冷却分钟）
- ``skipped_service_cooldown``  服务级聚合冷却拦截（P1：同服务任意白名单告警
                         在服务冷却期内不重复开查，含先前触发告警名）
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import structlog

from src.watchdog.mapping import map_alert

log = structlog.get_logger()

# 白名单：pod 类 4 项（2026-09-16 从云端 Prometheus /api/v1/rules 实测校准：
# KubeContainerOOMKilled 不在规则集中，OOM 以 KubePodCrashLooping(reason=OOMKilled)
# 形式出现；KubeDeploymentReplicasMismatch 实际存在，otel-demo 服务多为 Deployment）
# + 黄金指标 4 项（P1：延迟/错误率；批次1：CLIENT 错误率 011 补盲 + TelemetryAbsent
#   010 低流量补盲——absent_over_time 指标流缺席，Pyrra SLOMetricAbsent 同思想）。
DEFAULT_WHITELIST: frozenset[str] = frozenset({
    "KubePodCrashLooping",
    "KubePodNotReady",
    "KubeStatefulSetReplicasMismatch",
    "KubeDeploymentReplicasMismatch",
    "OtelDemoHighLatencyP99",
    "OtelDemoHighErrorRate",
    "OtelDemoHighClientErrorRate",
    "OtelDemoTelemetryAbsent",
})

TARGET_NAMESPACE = "otel-demo"
STATE_FILENAME = "state.json"


def _parse_iso(ts: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


class Alerter:
    """Prometheus alert polling + noise filtering + dedup/cooldown state machine."""

    def __init__(
        self,
        prometheus_url: str | None = None,
        whitelist: frozenset[str] | set[str] = DEFAULT_WHITELIST,
        namespace: str = TARGET_NAMESPACE,
        cooldown_min: int = 45,
        max_per_hour: int = 6,
        service_cooldown_min: int = 45,
        state_dir: str | Path = "artifacts/watchdog",
    ) -> None:
        self._url = (prometheus_url or os.getenv("PROMETHEUS_URL", "http://localhost:9090")).rstrip("/")
        self._whitelist = frozenset(whitelist)
        self._namespace = namespace
        self._cooldown = timedelta(minutes=cooldown_min)
        self._max_per_hour = max_per_hour
        # P1 服务级聚合冷却：同 service 任意白名单告警在窗口内只调查一次（跨告警名）。
        # 0 = 关闭聚合（回退 P0 纯指纹行为）。
        self._service_cooldown = timedelta(minutes=service_cooldown_min)
        self._state_dir = Path(state_dir)
        self._state_path = self._state_dir / STATE_FILENAME
        self._state = self._load_state()

    # ── network (the only IO besides the state file) ───────────────────────────

    def fetch_alerts(self) -> list[dict[str, object]]:
        """Fetch firing/pending alerts from Prometheus /api/v1/alerts (timeout 10s)."""
        resp = httpx.get(f"{self._url}/api/v1/alerts", timeout=10.0)
        resp.raise_for_status()
        return resp.json().get("data", {}).get("alerts", [])

    # ── state persistence (JSON on disk; survives restarts) ────────────────────

    def _load_state(self) -> dict[str, object]:
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("state root is not a JSON object")
            fps = raw.get("fingerprints")
            recents = raw.get("recent_investigations")
            svc_last = raw.get("service_last_investigated")
            return {
                "fingerprints": fps if isinstance(fps, dict) else {},
                "recent_investigations": recents if isinstance(recents, list) else [],
                # P1 新增：旧 state.json 无此键 → 视为空（向后兼容，P0 文件直接可读）
                "service_last_investigated": svc_last if isinstance(svc_last, dict) else {},
            }
        except FileNotFoundError:
            return {
                "fingerprints": {},
                "recent_investigations": [],
                "service_last_investigated": {},
            }
        except (json.JSONDecodeError, ValueError, OSError) as e:
            log.warning("state_load_failed_rebuilding", path=str(self._state_path), error=str(e))
            return {
                "fingerprints": {},
                "recent_investigations": [],
                "service_last_investigated": {},
            }

    def save_state(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    # ── fingerprinting ──────────────────────────────────────────────────────────

    @staticmethod
    def fingerprint(alertname: str, namespace: str, service: str) -> str:
        """fp = sha1(alertname + namespace + service)[:8]."""
        return hashlib.sha1(f"{alertname}{namespace}{service}".encode()).hexdigest()[:8]

    # ── budget helpers ──────────────────────────────────────────────────────────

    def _prune_recent(self, now: datetime) -> int:
        """Drop entries older than 1h from recent_investigations; return live count."""
        cutoff = now - timedelta(hours=1)
        kept = [
            ts
            for ts in self._state["recent_investigations"]  # type: ignore[index]
            if (dt := _parse_iso(ts)) is not None and dt > cutoff
        ]
        self._state["recent_investigations"] = kept
        return len(kept)

    # ── core state machine ──────────────────────────────────────────────────────

    def process(
        self, alerts: list[dict[str, object]], now: datetime | None = None
    ) -> list[dict[str, object]]:
        """Filter + dedup + cooldown + hourly budget for one polling cycle.

        Returns the list of passed items (each a map_alert dict augmented with
        ``fingerprint``). Does NOT mutate cooldown state — call mark_investigated()
        when an investigation actually starts, so that a passed-but-not-run alert
        (e.g. backends not ready) is retried on the next cycle.
        """
        now = now or datetime.now(UTC)
        passed: list[dict[str, object]] = []
        hourly_used = self._prune_recent(now)
        # P1.5（D-P1-01 修复）：同轮 cycle-local 服务表（service → 本轮首个通过
        # 全部检查的告警名）。持久表 service_last_investigated 由
        # mark_investigated() 在 process() 返回后才写，拦不住同一轮内到达的第二条
        # 同服务告警（E2E 001 实证：同轮 2 条 checkout → 2 次调查）——本表补齐该层。
        # --service-cooldown-min 0（关闭聚合）时本表不启用，回退纯指纹行为。
        cycle_services: dict[str, str] = {}

        for alert in alerts:
            labels: dict[str, str] = alert.get("labels", {}) or {}  # type: ignore[assignment]
            alertname = labels.get("alertname", "")
            namespace = labels.get("namespace", "")

            if alertname not in self._whitelist:
                log.info("alert_filtered", alertname=alertname, namespace=namespace,
                         pod=labels.get("pod", ""), reason="not_in_whitelist")
                continue
            if namespace != self._namespace:
                log.info("alert_filtered", alertname=alertname, namespace=namespace,
                         pod=labels.get("pod", ""), reason="wrong_namespace")
                continue

            item = map_alert(alert, now=now)
            fp = self.fingerprint(alertname, namespace, str(item["service_hint"]))
            item["fingerprint"] = fp

            entry = self._state["fingerprints"].get(fp)  # type: ignore[index]
            last = None
            if isinstance(entry, dict):
                last = _parse_iso(entry.get("last_investigated_at", ""))
            if last is not None and now - last < self._cooldown:
                remaining_min = int((self._cooldown - (now - last)).total_seconds() // 60) + 1
                log.info("skipped_cooldown", fingerprint=fp, alertname=alertname,
                         service=item["service_hint"], remaining_min=remaining_min)
                continue

            # ── P1 第二层去重：服务级聚合冷却（同 service 任意白名单告警不重复开查）──
            if self._service_cooldown > timedelta(0):
                service = str(item["service_hint"])
                # 同轮内该服务已有一条通过全部检查 → 拦截（D-P1-01：cycle-local）
                if service in cycle_services:
                    log.info("skipped_service_cooldown", alertname=alertname,
                             service=service,
                             remaining_min=int(self._service_cooldown.total_seconds() // 60),
                             first_alertname=cycle_services[service],
                             reason="same_cycle")
                    continue
                svc_last_ts = _parse_iso(
                    self._state["service_last_investigated"].get(service, "")  # type: ignore[union-attr]
                )
                if svc_last_ts is not None and now - svc_last_ts < self._service_cooldown:
                    remaining_min = int(
                        (self._service_cooldown - (now - svc_last_ts)).total_seconds() // 60
                    ) + 1
                    log.info("skipped_service_cooldown", alertname=alertname,
                             service=service, remaining_min=remaining_min,
                             first_alertname=self._first_alertname_for(service))
                    continue

            if hourly_used >= self._max_per_hour:
                log.info("alert_filtered", alertname=alertname, namespace=namespace,
                         pod=labels.get("pod", ""), reason="hourly_limit_exceeded")
                continue

            log.info("alert_seen", alertname=alertname, namespace=namespace,
                     service=item["service_hint"], fingerprint=fp,
                     active_at=item["active_at"])
            passed.append(item)
            if self._service_cooldown > timedelta(0):
                # 通过全部检查 → 记入 cycle-local 服务表（本轮后续同服务将被拦）
                cycle_services.setdefault(str(item["service_hint"]), alertname)
            hourly_used += 1  # 同轮多条也预占小时额度（成本护栏，宁可少查不可超限）

        return passed

    def _first_alertname_for(self, service: str) -> str:
        """Latest fingerprint entry's alertname for a service (for skipped_service_cooldown)."""
        best_ts: datetime | None = None
        best_name = ""
        fps = self._state["fingerprints"]
        if isinstance(fps, dict):
            for entry in fps.values():
                if isinstance(entry, dict) and entry.get("service") == service:
                    ts = _parse_iso(entry.get("last_investigated_at", ""))
                    if ts is not None and (best_ts is None or ts > best_ts):
                        best_ts, best_name = ts, str(entry.get("alertname", ""))
        return best_name

    def mark_investigated(self, item: dict[str, object], now: datetime | None = None) -> None:
        """Record that an investigation started: fingerprint + service + hourly count."""
        now = now or datetime.now(UTC)
        self._state["fingerprints"][str(item["fingerprint"])] = {  # type: ignore[index]
            "alertname": str(item["alertname"]),
            "service": str(item["service_hint"]),
            "last_investigated_at": now.isoformat(),
        }
        self._state["recent_investigations"].append(now.isoformat())  # type: ignore[union-attr]
        # P1：服务级聚合冷却时间戳（同 service 后续任意白名单告警将被拦）
        self._state["service_last_investigated"][str(item["service_hint"])] = now.isoformat()  # type: ignore[index]
        self.save_state()
