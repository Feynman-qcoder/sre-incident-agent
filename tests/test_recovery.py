"""恢复测试自动化——三层中断恢复语义钉死（add-recovery-tests，2026-09-19）。

守护对象 = 三层中断恢复语义（行为契约，即本次用例逐条断言的规范）：

| 层 | 语义 | 用例 |
|---|---|---|
| ① 调查开始前失败（后端不可达） | **不占指纹**、下一轮立即重试 | B |
| ② 调查中途 crash | 指纹**预占**（mark 在调查前）→ 45min 冷却拦截 → 到期重查 | A |
| ③ 毒告警隔离 | 预占指纹使永久失败调查每个冷却窗口至多一次（损失封顶） | C |

零 LLM 零集群零网络。stub 调查函数 = 闭包计数器 + 可编程异常。
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from structlog.testing import capture_logs

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.watchdog.alerter import Alerter  # noqa: E402
from tests.test_watchdog import FIXED_NOW, make_crash_alert  # noqa: E402 — 复用既有 helper

T0 = FIXED_NOW  # fake clock 起点（2026-09-16 13:00Z，与既有测试同一时间轴）
COOLDOWN = timedelta(minutes=45)


class StubInvestigator:
    """可编程 stub：记录调用时刻（fake now），支持永久失败模式。

    fail_forever=True 时记录调用但不抛异常——等价生产语义
    （src/watchdog/runner.py 的 run_investigation：内部重试 3 次耗尽后
    log.error 并返回 None，**不向调用方传播**——毒告警不会中断轮询循环）。
    """

    def __init__(self, fail_forever: bool = False) -> None:
        self.calls: list[datetime] = []
        self.failed_calls: list[datetime] = []
        self.fail_forever = fail_forever

    def __call__(self, item: dict[str, object], now: datetime, **kw: object) -> None:
        self.calls.append(now)
        if self.fail_forever:
            # 模拟 runner 重试耗尽的终态：调查失败但循环继续
            self.failed_calls.append(now)


def _cycle(
    alerter: Alerter, stub: StubInvestigator, now: datetime,
    backends_ready: bool = True, interrupt: KeyboardInterrupt | None = None,
) -> list[dict[str, object]]:
    """与 scripts/watchdog.py 主循环/`_replay` 同构的单轮语义
    （backend 检查 → mark 预占 → 调查；backends 未就绪不 mark）。
    差异仅一点：mark_investigated 注入 fake now（`_replay` 用系统时钟——
    语义时序完全一致，见 TestReplayPathParity 对真实 `_replay` 的直测）。
    """
    passed = alerter.process([make_crash_alert("checkout")], now=now)
    for item in passed:
        if not backends_ready:
            continue  # 与 watchdog.py:150 一致：skip 本轮，不写指纹
        alerter.mark_investigated(item, now=now)  # 与 watchdog.py:155 一致：调查前预占
        if interrupt is not None:
            raise interrupt  # 模拟调查中途进程被杀（mark 已落盘）
        stub(item, now=now)  # type: ignore[call-arg]
    return passed


def _state_has_fingerprint(state_dir: Path) -> bool:
    import json
    p = state_dir / "state.json"
    if not p.exists():
        return False
    st = json.loads(p.read_text(encoding="utf-8"))
    return len(st.get("fingerprints", {})) > 0


class TestLayer2MidCrashCooldownRetry:
    """层②：中途 crash → 冷却 → 到期重查（勘误 §1 表第 ② 行）。"""

    def test_mid_crash_marks_fingerprint_then_cooldown_then_retry(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "wd"
        stub = StubInvestigator()

        # ── 第 1 轮：调查中途进程被杀（KeyboardInterrupt 穿透重试）──
        a1 = Alerter(state_dir=state_dir, cooldown_min=45, max_per_hour=100)
        with pytest.raises(KeyboardInterrupt):
            _cycle(a1, stub, now=T0, interrupt=KeyboardInterrupt())
        # 勘误后的准确语义：mark 在调查前 → state.json 已含该指纹
        assert _state_has_fingerprint(state_dir), \
            "勘误 §1②：mark_investigated 在调查开始前执行，crash 时指纹已预占"
        assert len(stub.calls) == 0  # 调查未完成（stub 是调用即记，crash 前未到达）

        # ── 重启：新 Alerter 实例（磁盘重载）──
        a2 = Alerter(state_dir=state_dir, cooldown_min=45, max_per_hour=100)

        # ── 第 2 轮（+1min，冷却期内）：同告警 → 冷却拦截 ──
        with capture_logs() as logs:
            passed = _cycle(a2, stub, now=T0 + timedelta(minutes=1))
        assert passed == []
        assert any(lg["event"] == "skipped_cooldown" for lg in logs)
        assert len(stub.calls) == 0

        # ── 第 3 轮（+46min，冷却到期）：告警仍 firing → 重查（延迟 at-least-once）──
        passed = _cycle(a2, stub, now=T0 + timedelta(minutes=46))
        assert len(passed) == 1
        assert len(stub.calls) == 1, "冷却到期后必须重查——层② 的 at-least-once 语义"


class TestLayer1BackendNotReadyImmediateRetry:
    """层①：后端未就绪 → 不占指纹、立即重试（勘误 §1 表第 ① 行）。"""

    def test_backend_down_skips_without_mark_then_immediate_retry(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "wd"
        stub = StubInvestigator()

        # ── 第 1 轮：后端未就绪 → skip，不写指纹 ──
        a1 = Alerter(state_dir=state_dir, cooldown_min=45, max_per_hour=100)
        passed = _cycle(a1, stub, now=T0, backends_ready=False)
        assert len(passed) == 1  # 告警本身通过了过滤（passed 有）
        assert not _state_has_fingerprint(state_dir), \
            "层①：backends 未就绪路径不写指纹（P0 验收 #4 死端口法实测的语义）"
        assert len(stub.calls) == 0

        # ── 第 2 轮（同一时刻，不推时钟）：后端恢复 → 立即开查 ──
        with capture_logs() as logs:
            _cycle(a1, stub, now=T0, backends_ready=True)
        assert len(stub.calls) == 1, "后端恢复当轮立即重试——无需等冷却"
        assert not any(lg["event"] == "skipped_cooldown" for lg in logs), \
            "未占指纹的证据：同 fake 时刻重查不被冷却拦截"


class TestLayer3PoisonAlertLossCapped:
    """层③：毒告警损失封顶（勘误 §1 表第 ③ 行）——每个冷却窗口至多一次。"""

    def test_poison_alert_at_most_once_per_cooldown_window(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "wd"
        stub = StubInvestigator(fail_forever=True)

        a = Alerter(state_dir=state_dir, cooldown_min=45, max_per_hour=100)

        # t=0：首次调查（mark 预占 → stub 永久失败——普通 Exception = runner 内重试耗尽后的
        # 等价简化：生产语义是 run_investigation 重试 3 次后放弃（run_investigation 的
        # max_retries 循环在 src/watchdog/runner.py），此处 stub 直接抛 = 重试已耗尽的终态）
        _cycle(a, stub, now=T0)
        assert len(stub.calls) == 1
        assert _state_has_fingerprint(state_dir), "毒告警首次调查即预占指纹"

        # t=+10min：冷却期内 → 拦截（calls 不增）
        _cycle(a, stub, now=T0 + timedelta(minutes=10))
        assert len(stub.calls) == 1

        # t=+46min：窗口 1 到期 → 重查一次又失败
        _cycle(a, stub, now=T0 + timedelta(minutes=46))
        assert len(stub.calls) == 2

        # t=+92min：窗口 2 到期 → 再重查一次
        _cycle(a, stub, now=T0 + timedelta(minutes=92))
        assert len(stub.calls) == 3

        # 封顶断言：任意相邻两次调用间隔 ≥45min（每冷却窗口至多一次）
        for earlier, later in zip(stub.calls, stub.calls[1:], strict=False):
            assert later - earlier >= COOLDOWN, \
                "层③：永久失败的调查每 45min 冷却窗口至多重试一次——损失封顶语义"


class TestReplayPathParity:
    """对真实 `scripts/watchdog.py` 路径的直测（real clock）：
    上面三个用例的内联循环与 `_replay`/主循环同构——本用例钉死 `_replay` 自身的
    mark 时序（调查前预占），防止未来重构把 mark 挪到调查后（层②③ 失效）。
    """

    def test_replay_marks_before_investigation_crash_keeps_fingerprint(
        self, tmp_path: Path,
    ) -> None:
        from scripts.watchdog import _replay

        state_dir = tmp_path / "wd"
        fixture = tmp_path / "alerts.jsonl"
        # 每行 = 一个轮次的 alerts 数组（单层）
        fixture.write_text(
            json_dumps([make_crash_alert("checkout")]) + "\n", encoding="utf-8")

        def crashing_investigation(item: dict, **kw: object) -> None:
            raise KeyboardInterrupt("killed mid-investigation")

        alerter = Alerter(state_dir=state_dir, cooldown_min=45, max_per_hour=100)
        args = SimpleNamespace(
            replay_alerts=str(fixture), dry_run=False, no_notify=True,
            notify_webhook=None,
        )
        with pytest.raises(KeyboardInterrupt):
            _replay(args, alerter, crashing_investigation, lambda: True)
        # `_replay` 真实路径：mark（watchdog.py:100）在 run_investigation_fn 之前
        assert _state_has_fingerprint(state_dir), \
            "_replay 的 mark 必须在调查前——层②③ 的共同前提"


def json_dumps(obj: object) -> str:
    import json
    return json.dumps(obj)
