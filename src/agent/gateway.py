"""Safe Tool Gateway — "模型负责决定查什么，程序决定能不能查"（add-tool-gateway D1-D5）。

单入口 ``SafeToolGateway.check_and_invoke(tool_name, args, ctx)``，四类钳制：
1. Allowlist：未注册工具名 → DENY(not_in_allowlist)；
2. Namespace：get_pod_events / get_service_topology 的 namespace 越界 → DENY；
3. Query Window：range/loki/traces 的 start/end 超调查窗口 ± margin → CLAMP 且
   结果头部显式声明（禁止静默裁剪——D2 告知式钳制）；
4. Budget + Timeout：per-run 调用数硬上限（默认 20 = mem-inject-on 实测最大 17
   + 余量；D5 默认值=现状上界），耗尽 DENY + 收敛引导；单工具超时返回 [TOOL TIMEOUT]。

审计（D4，与 tool_calls_log 职责分离）：每次判定追加写 tool_audit.jsonl
（incident_id/tool/args_summary≤200/verdict/reason/latency_ms/error/ts）——
含被拒调用；**被 DENY 的调用绝不进 tool_calls_log**（grounding 完整性）。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

DEFAULT_ALLOWLIST = frozenset({
    "query_prometheus_range", "query_prometheus_instant", "search_traces",
    "get_trace", "query_loki", "get_pod_events", "get_service_topology",
})
NAMESPACE_TOOLS = {"get_pod_events", "get_service_topology"}
WINDOW_TOOLS = {"query_prometheus_range", "search_traces", "query_loki"}
BUDGET_EXHAUSTED_MSG = (
    "Tool budget exhausted. Generate your final report now."
)


def _parse_ts(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class SafeToolGateway:
    """Deterministic policy layer between the LLM and the tool map."""

    def __init__(
        self,
        tool_map: dict[str, Any],
        audit_path: str | Path | None = None,
        incident_id: str = "",
    ) -> None:
        self._tool_map = tool_map
        self._incident_id = incident_id
        # audit_path 未传 → 系统 tmp（spec：单测/无 run_id 场景）
        if audit_path is None:
            self._audit_path = Path(tempfile.gettempdir()) / "tool_audit.jsonl"
        else:
            self._audit_path = Path(audit_path)
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._call_count = 0
        # 环境变量配置（Req 3：默认值即安全值 = 实测行为上界）
        allow_env = os.getenv("TOOL_ALLOWLIST", "")
        self._allowlist = (frozenset(s.strip() for s in allow_env.split(",") if s.strip())
                           if allow_env else DEFAULT_ALLOWLIST)
        ns_env = os.getenv("TOOL_ALLOWED_NAMESPACES", "")
        self._namespaces = ({s.strip() for s in ns_env.split(",") if s.strip()}
                            if ns_env else {"otel-demo"})
        self._margin_min = int(os.getenv("TOOL_QUERY_WINDOW_MARGIN_MIN", "30"))
        self._budget = int(os.getenv("TOOL_BUDGET", "20"))
        self._timeout_s = float(os.getenv("TOOL_TIMEOUT_S", "15"))

    # ── audit ──────────────────────────────────────────────────────────────

    def _audit(self, tool: str, args_summary: str, verdict: str,
               reason: str, latency_ms: float, error: str = "") -> None:
        entry = {
            "incident_id": self._incident_id,
            "tool": tool,
            "args_summary": args_summary[:200],
            "verdict": verdict,
            "reason": reason,
            "latency_ms": round(latency_ms, 1),
            "error": error[:200],
            "ts": datetime.now(UTC).isoformat(),
        }
        try:
            with self._audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("tool_audit_write_failed", error=repr(e)[:150])

    @staticmethod
    def _summarize(args: dict[str, Any]) -> str:
        return json.dumps(args, ensure_ascii=False, default=str)

    # ── core ───────────────────────────────────────────────────────────────

    def check_and_invoke(
        self, tool_name: str, args: dict[str, Any],
        ctx: dict[str, Any] | None = None,
    ) -> tuple[str, bool]:
        """Policy gate + invoke. Returns (result_str, executed).

        executed=False（DENY）时 result_str 是给模型的可理解文本；
        调用方据此决定是否记入 tool_calls_log（DENY 绝不记——D4）。
        """
        ctx = ctx or {}
        args_summary = self._summarize(args)
        # 审计的 incident_id：ctx 传入（graph state）优先于构造时缺省
        if ctx.get("incident_id"):
            self._incident_id = str(ctx["incident_id"])

        # 1. Allowlist（含未知工具名——原 [UNKNOWN TOOL] 软提示的硬升级）
        if tool_name not in self._allowlist or tool_name not in self._tool_map:
            self._audit(tool_name, args_summary, "DENY", "not_in_allowlist", 0.0)
            log.info("gateway_deny", tool=tool_name, reason="not_in_allowlist")
            return (f"[TOOL DENIED: {tool_name} is not in the allowlist. "
                    "Use only the provided investigation tools.]"), False

        # 2. Namespace scope（K8s 类工具）
        if tool_name in NAMESPACE_TOOLS:
            ns = str(args.get("namespace", ""))
            if ns and ns not in self._namespaces:
                self._audit(tool_name, args_summary, "DENY", "namespace_out_of_scope", 0.0)
                log.info("gateway_deny", tool=tool_name, reason="namespace_out_of_scope",
                         namespace=ns)
                return (f"[TOOL DENIED: namespace '{ns}' is out of scope "
                        f"(allowed: {sorted(self._namespaces)}).]"), False

        # 3. Query window clamp（告知式，禁止静默——D2）
        clamped_note = ""
        if tool_name in WINDOW_TOOLS and ctx.get("incident_start_ts"):
            args, clamped_note = self._clamp_window(args, ctx)

        # 4. Budget（per-run 硬上限）
        if self._call_count >= self._budget:
            self._audit(tool_name, args_summary, "DENY", "budget_exhausted", 0.0)
            log.info("gateway_deny", tool=tool_name, reason="budget_exhausted",
                     budget=self._budget)
            return f"[TOOL DENIED: {BUDGET_EXHAUSTED_MSG}]", False
        self._call_count += 1

        # Invoke with timeout（超时返回文本不崩）
        started = time.monotonic()
        try:
            result, error = self._invoke_with_timeout(self._tool_map[tool_name], args)
        except Exception as e:  # noqa: BLE001 — 工具自身异常照旧 [TOOL ERROR] 语义
            latency = (time.monotonic() - started) * 1000
            self._audit(tool_name, args_summary, "ALLOW", "executed_error",
                        latency, error=repr(e))
            return f"[TOOL ERROR: {e}]", True

        latency = (time.monotonic() - started) * 1000
        verdict = "CLAMP" if clamped_note else "ALLOW"
        reason = "window_clamped" if clamped_note else "executed"
        if result is None:  # timeout
            self._audit(tool_name, args_summary, "DENY", "timeout", latency,
                        error=f"exceeded {self._timeout_s}s")
            log.info("gateway_timeout", tool=tool_name, timeout_s=self._timeout_s)
            return f"[TOOL TIMEOUT: {tool_name} exceeded {self._timeout_s}s]", False
        self._audit(tool_name, args_summary, verdict, reason, latency)
        if clamped_note:
            return f"{clamped_note}\n{result}", True
        return str(result), True

    def _clamp_window(self, args: dict[str, Any],
                      ctx: dict[str, Any]) -> tuple[dict[str, Any], str]:
        start = _parse_ts(args.get("start"))
        end = _parse_ts(args.get("end"))
        win_start = _parse_ts(ctx.get("incident_start_ts"))
        win_end = _parse_ts(ctx.get("incident_end_ts"))
        if not (start and end and win_start and win_end):
            return args, ""
        margin = timedelta(minutes=self._margin_min)
        lo, hi = win_start - margin, win_end + margin
        new_start = max(start, lo)
        new_end = min(end, hi)
        if new_start == start and new_end == end:
            return args, ""
        clamped = dict(args)
        clamped["start"] = new_start.isoformat()
        clamped["end"] = new_end.isoformat()
        note = (f"[window clamped: {start.isoformat()} → {new_start.isoformat()} / "
                f"{end.isoformat()} → {new_end.isoformat()} — query window limited to the "
                f"incident window ± {self._margin_min}m]")
        log.info("gateway_clamp", tool=clamped.get("start", "")[:0] or "window",
                 margin_min=self._margin_min)
        return clamped, note

    def _invoke_with_timeout(self, tool: Any, args: dict[str, Any]) -> tuple[Any, bool]:
        """Run tool.invoke(args) in a thread; (None, True) on timeout, (result, False) ok."""
        box: dict[str, Any] = {}
        done = threading.Event()

        def _run() -> None:
            try:
                box["result"] = tool.invoke(args)
            except BaseException as e:  # noqa: B036 — re-raised in caller
                box["error"] = e
            finally:
                done.set()

        t = threading.Thread(target=_run, daemon=True, name="gateway-tool")
        t.start()
        if not done.wait(self._timeout_s):
            return None, True
        if "error" in box:
            raise box["error"]
        return box.get("result"), False
