"""Tests for add-tool-gateway（零 LLM，stub 工具 + tmp 审计）。

tasks 1.4 清单：7 工具全 ALLOW / 未知名 DENY / kube-system DENY / 超窗 CLAMP
且结果含声明 / budget 第 21 次 DENY + 收敛文案 / 超时不崩 / DENY 不进
tool_calls_log 而 audit 有 / 审计字段完整 / 环境变量覆盖默认 / 默认参数等价。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.gateway import BUDGET_EXHAUSTED_MSG, SafeToolGateway  # noqa: E402

CTX = {
    "incident_id": "watchdog-KubePodNotReady-3d474e83",
    "incident_start_ts": "2026-09-18T12:00:00+00:00",
    "incident_end_ts": "2026-09-18T12:05:00+00:00",
}
TOOL_NAMES = [
    "query_prometheus_range", "query_prometheus_instant", "search_traces",
    "get_trace", "query_loki", "get_pod_events", "get_service_topology",
]


class _StubTool:
    """最小工具 stub：invoke 记录调用并返回固定文本。"""

    def __init__(self, name: str, delay: float = 0.0, result: str = "stub-result") -> None:
        self.name = name
        self.calls: list[dict] = []
        self.delay = delay
        self.result = result

    def invoke(self, args: dict) -> str:
        self.calls.append(args)
        if self.delay:
            time.sleep(self.delay)
        return self.result


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    return tmp_path / "audit" / "tool_audit.jsonl"


def _gateway(audit_path: Path, tools: dict[str, _StubTool] | None = None
             ) -> tuple[SafeToolGateway, dict[str, _StubTool]]:
    tool_map = tools or {n: _StubTool(n) for n in TOOL_NAMES}
    return SafeToolGateway(tool_map, audit_path=audit_path,
                           incident_id=CTX["incident_id"]), tool_map


def _read_audit(audit_path: Path) -> list[dict]:
    return [json.loads(ln) for ln in
            audit_path.read_text(encoding="utf-8").splitlines() if ln.strip()]


class TestAllow:
    def test_all_seven_tools_allow_fast_path(self, audit_path: Path) -> None:
        """① 7 工具全部 ALLOW 快路径（含典型参数形态）。"""
        gw, tool_map = _gateway(audit_path)
        for name, args in [
            ("query_prometheus_range", {"query": "rate(x)", "start": "2026-09-18T11:45:00+00:00",
                                        "end": "2026-09-18T12:20:00+00:00"}),
            ("query_prometheus_instant", {"query": "up"}),
            ("search_traces", {"service": "checkout", "start": "2026-09-18T11:45:00+00:00",
                               "end": "2026-09-18T12:20:00+00:00"}),
            ("get_trace", {"trace_id": "abc123"}),
            ("query_loki", {"logql": "{s=\"x\"}", "start": "2026-09-18T11:45:00+00:00",
                            "end": "2026-09-18T12:20:00+00:00"}),
            ("get_pod_events", {"namespace": "otel-demo", "pod_prefix": "checkout"}),
            ("get_service_topology", {"namespace": "otel-demo"}),
        ]:
            result, executed = gw.check_and_invoke(name, args, CTX)
            assert executed is True, f"{name} should ALLOW"
            assert "DENIED" not in result and "clamped" not in result
        audit = _read_audit(audit_path)
        assert len(audit) == 7
        assert all(e["verdict"] == "ALLOW" for e in audit)

    def test_default_params_behavior_equivalent(self, audit_path: Path) -> None:
        """⑩ 默认参数（不设任何 TOOL_* env）下行为等价——窗口内查询零改写。"""
        gw, tool_map = _gateway(audit_path)
        in_window = {"query": "rate(x)", "start": "2026-09-18T11:59:00+00:00",
                     "end": "2026-09-18T12:06:00+00:00"}
        result, executed = gw.check_and_invoke("query_prometheus_range", in_window, CTX)
        assert executed and result == "stub-result"  # 无 clamp 声明，参数原样透传
        assert tool_map["query_prometheus_range"].calls[0] == in_window


class TestDeny:
    def test_unknown_tool_denied(self, audit_path: Path) -> None:
        """② 未注册工具名 → DENY(not_in_allowlist)，可理解文本。"""
        gw, _ = _gateway(audit_path)
        result, executed = gw.check_and_invoke("rm_rf_everything", {"path": "/"}, CTX)
        assert executed is False
        assert "not in the allowlist" in result or "DENIED" in result
        audit = _read_audit(audit_path)
        assert audit[-1]["verdict"] == "DENY" and audit[-1]["reason"] == "not_in_allowlist"

    def test_namespace_out_of_scope_denied(self, audit_path: Path) -> None:
        """③ kube-system 越界 → DENY(namespace_out_of_scope)，kube 数据未被查询。"""
        gw, tool_map = _gateway(audit_path)
        result, executed = gw.check_and_invoke(
            "get_pod_events", {"namespace": "kube-system", "pod_prefix": "core"}, CTX)
        assert executed is False
        assert "out of scope" in result
        assert tool_map["get_pod_events"].calls == []  # 未执行
        audit = _read_audit(audit_path)
        assert audit[-1]["reason"] == "namespace_out_of_scope"

    def test_budget_exhausted_on_call_21(self, audit_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
        """⑤ TOOL_BUDGET=20：第 21 次 DENY + 收敛引导文案。"""
        monkeypatch.setenv("TOOL_BUDGET", "20")
        gw, tool_map = _gateway(audit_path)
        ok = 0
        for i in range(21):
            result, executed = gw.check_and_invoke(
                "query_prometheus_instant", {"query": f"q{i}"}, CTX)
            if executed:
                ok += 1
            else:
                assert i == 20, "only the 21st call should be denied"
                assert BUDGET_EXHAUSTED_MSG in result
        assert ok == 20

    def test_timeout_returns_text_not_crash(self, audit_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
        """⑥ 超时返回 [TOOL TIMEOUT] 不崩。"""
        monkeypatch.setenv("TOOL_TIMEOUT_S", "0.2")
        slow = _StubTool("query_prometheus_instant", delay=1.5)
        gw = SafeToolGateway({"query_prometheus_instant": slow},
                             audit_path=audit_path, incident_id="i")
        result, executed = gw.check_and_invoke(
            "query_prometheus_instant", {"query": "slow"}, CTX)
        assert executed is False
        assert "[TOOL TIMEOUT" in result
        audit = _read_audit(audit_path)
        assert audit[-1]["reason"] == "timeout"


class TestClamp:
    def test_window_clamped_with_visible_note(self, audit_path: Path) -> None:
        """④ 7 天窗口 → CLAMP 到调查窗口±30m，结果头部显式声明，非静默。"""
        gw, tool_map = _gateway(audit_path)
        wide = {"query": "rate(x)", "start": "2026-09-11T12:00:00+00:00",
                "end": "2026-09-18T12:05:00+00:00"}
        result, executed = gw.check_and_invoke("query_prometheus_range", wide, CTX)
        assert executed is True
        assert result.startswith("[window clamped:")
        executed_args = tool_map["query_prometheus_range"].calls[0]
        # 新 start = 调查窗口起点 - 30min = 11:30，end 不变（在界内）
        assert executed_args["start"] == "2026-09-18T11:30:00+00:00"
        audit = _read_audit(audit_path)
        assert audit[-1]["verdict"] == "CLAMP" and audit[-1]["reason"] == "window_clamped"


class TestAuditSeparation:
    def test_deny_in_audit_not_in_tool_calls_log(self, audit_path: Path) -> None:
        """⑦ 双向断言：DENY 调用 audit 有记录 + tool_calls_log 无（D4）。"""
        gw, _ = _gateway(audit_path)
        _, e1 = gw.check_and_invoke("get_service_topology",
                                    {"namespace": "kube-system"}, CTX)
        _, e2 = gw.check_and_invoke("get_service_topology",
                                    {"namespace": "otel-demo"}, CTX)
        _, e3 = gw.check_and_invoke("evil_tool", {}, CTX)
        assert (e1, e2, e3) == (False, True, False)
        audit = _read_audit(audit_path)
        assert len(audit) == 3  # 全部进审计（含 2 次 DENY）
        # 模拟 graph 的 log 收集（只记 executed）
        tool_calls_log = [e for e, ex in [(1, e1), (2, e2), (3, e3)] if ex]
        assert tool_calls_log == [2]  # 只有 ALLOW 的进 log

    def test_audit_fields_complete(self, audit_path: Path) -> None:
        """⑧ 审计字段完整性（8 键 + args_summary 截断 200）。"""
        gw, _ = _gateway(audit_path)
        gw.check_and_invoke(
            "query_loki",
            {"logql": "{s='" + "x" * 500 + "'}", "start": "2026-09-18T11:45:00+00:00",
             "end": "2026-09-18T12:20:00+00:00"}, CTX)
        entry = _read_audit(audit_path)[-1]
        for key in ("incident_id", "tool", "args_summary", "verdict",
                    "reason", "latency_ms", "error", "ts"):
            assert key in entry, f"missing audit field: {key}"
        assert entry["incident_id"] == CTX["incident_id"]
        assert len(entry["args_summary"]) <= 200


class TestConfig:
    def test_env_overrides_defaults(self, audit_path: Path,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
        """⑨ 环境变量覆盖默认：TOOL_ALLOWED_NAMESPACES 扩展后原越界变 ALLOW。"""
        monkeypatch.setenv("TOOL_ALLOWED_NAMESPACES", "otel-demo,monitoring")
        gw, _ = _gateway(audit_path)
        _, executed = gw.check_and_invoke(
            "get_pod_events", {"namespace": "monitoring", "pod_prefix": "x"}, CTX)
        assert executed is True  # 扩展后放行
        # budget 覆盖：TOOL_BUDGET=2 → 第 3 次 DENY
        monkeypatch.setenv("TOOL_BUDGET", "2")
        gw2, _ = _gateway(audit_path)
        for expected in (True, True, False):
            _, ex = gw2.check_and_invoke("query_prometheus_instant", {"query": "q"}, CTX)
            assert ex is expected
