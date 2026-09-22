"""Map Prometheus alerts → investigation parameters. Pure functions, zero I/O.

契约（任务书 §4.1）：输入告警 dict，输出
``{namespace, service_hint, fault_type_hint, window_start, window_end}``。

pod 名 → 服务名的提取规则：
  ``otel-demo-<service>-<hash>-<hash>``   (Deployment pod)
  ``otel-demo-<service>-<ordinal>``       (StatefulSet pod)

注意：OTel Astronomy Shop 2.x 的服务名本身可含连字符（product-catalog、
fraud-detection、load-generator），机械"取第 2 段"会把 product-catalog 截断成
product。因此先按已知服务名单做最长前缀匹配，匹配失败再回退"第 2 段"启发式。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

# 与 src/datasources/live.py 的 ASTRONOMY_SHOP_SERVICES 保持同步（OTel Astronomy Shop 2.x）。
# 此处复制而非 import：保证本模块零第三方依赖（纯函数、可独立单测、低耦合）。
KNOWN_SERVICES: tuple[str, ...] = (
    "frontend", "cart", "checkout", "currency",
    "email", "payment", "product-catalog",
    "recommendation", "shipping", "ad",
    "load-generator", "accounting", "fraud-detection",
    "quote", "flagd",
)

# 白名单告警名 → 故障类型 hint（仅 hint，不强制；调查中 Agent 自行修正）
FAULT_TYPE_HINTS: dict[str, str] = {
    "KubePodCrashLooping": "pod_crash",
    "KubePodNotReady": "pod_crash",
    "KubeStatefulSetReplicasMismatch": "pod_crash",
    "KubeDeploymentReplicasMismatch": "pod_crash",
    # P1 黄金指标告警（golden-signal-alerting 能力，spanmetrics 同源查询）
    "OtelDemoHighLatencyP99": "high_latency",
    "OtelDemoHighErrorRate": "http_abort",
    "OtelDemoHighClientErrorRate": "http_abort",  # 批次1：网络分区/下游不可达（011 B→A）
    # 批次1：指标流缺席（010 低流量边界）——最常见根因是进程消失（pod 停/被杀），
    # 故 hint=pod_crash；仅 hint，最终归因仍由当前工具证据支撑。
    "OtelDemoTelemetryAbsent": "pod_crash",
}

# 调查窗口起点 = activeAt − 120s（spec：对齐 K8s 事件证据窗口）
WINDOW_LOOKBACK_S = 120

# Prometheus activeAt 可带纳秒精度（9 位小数），fromisoformat 只认 ≤6 位 → 截断
_NS_RE = re.compile(r"^(.*\.\d{6})\d+(.*)$")


def parse_prometheus_ts(ts: str) -> datetime | None:
    """Parse a Prometheus timestamp (e.g. activeAt, nanosecond precision + 'Z')."""
    if not ts:
        return None
    s = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        m = _NS_RE.match(s)
        if m:
            return datetime.fromisoformat(m.group(1) + m.group(2))
        return None


def service_from_pod(pod: str, services: tuple[str, ...] = KNOWN_SERVICES) -> str:
    """Extract the Astronomy-Shop service name from a pod name.

    Two naming schemes, both accepted:
    - ``otel-demo-<service>-<hash>-<hash>`` / ``otel-demo-<service>-<ordinal>``
      (spec template; some helm release prefixes)
    - ``<service>-<hash>-<hash>`` / ``<service>-<ordinal>``
      (OTel Astronomy Shop 2.x default: no namespace prefix, e.g.
      ``checkout-5df89485f4-572wp`` — verified on the live cluster 2026-09-16)

    Longest-prefix match against KNOWN_SERVICES first (handles hyphenated
    names like product-catalog); falls back to the "service segment" heuristic.
    """
    for svc in sorted(services, key=len, reverse=True):
        if pod.startswith(f"otel-demo-{svc}-"):
            return svc
    for svc in sorted(services, key=len, reverse=True):
        if pod.startswith(f"{svc}-"):
            return svc
    parts = pod.split("-")
    if pod.startswith("otel-demo-"):
        return parts[2] if len(parts) > 2 else pod
    return parts[0] if parts else pod


def fault_type_hint(alertname: str, labels: dict[str, str]) -> str:
    """crash-looping / not-ready → pod_crash；OOM 信号 → memory_stress（仅 hint）。"""
    reason = (labels.get("reason") or "").lower()
    if "oom" in reason or "oom" in alertname.lower():
        return "memory_stress"
    return FAULT_TYPE_HINTS.get(alertname, "unknown")


def map_alert(alert: dict[str, object], now: datetime | None = None) -> dict[str, object]:
    """Map one Prometheus alert to investigation parameters.

    Pure w.r.t. (alert, now): pass a fixed ``now`` in tests for deterministic output.
    Output keys: alertname / namespace / pod / service_hint / fault_type_hint /
    active_at / window_start / window_end (ISO-8601 UTC strings).
    """
    now = now or datetime.now(UTC)
    labels: dict[str, str] = alert.get("labels", {})  # type: ignore[assignment]
    alertname = labels.get("alertname", "")
    namespace = labels.get("namespace", "")
    pod = labels.get("pod", "")
    # 服务名解析优先级（P1 设计 §4.1）：
    # 1. service_name —— 黄金指标告警直接携带（值须为已知服务名，防脏数据）
    # 2. deployment   —— replicas-mismatch 类告警（2026-09-16 云端实测无有效 pod 标签）
    # 3. pod 名解析   —— pod 类告警（CrashLooping/NotReady）
    service_name = labels.get("service_name", "")
    deployment = labels.get("deployment", "")
    if service_name and service_name in KNOWN_SERVICES:
        service = service_name
    elif deployment and deployment in KNOWN_SERVICES:
        service = deployment
    else:
        service = service_from_pod(pod)
    active_at = parse_prometheus_ts(str(alert.get("activeAt", ""))) or now
    return {
        "alertname": alertname,
        "namespace": namespace,
        "pod": pod,
        "service_hint": service,
        "fault_type_hint": fault_type_hint(alertname, labels),
        "active_at": active_at.isoformat(),
        "window_start": (active_at - timedelta(seconds=WINDOW_LOOKBACK_S)).isoformat(),
        "window_end": now.isoformat(),
    }
