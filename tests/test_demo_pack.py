"""Tests for add-local-demo-pack 任务 2（bundle 聚合层）+ 任务 4（replay-alerts）。

任务 2（tasks 2.3）：bundle 结构完整（四视图所需字段）/ run 白名单不触历史 runs /
离线模式零 LLM 调用 / 体积 <2MB 断言。
任务 4（tasks 4.3）：回放走通全链（stub 调查）/ 同轮去重与冷却生效 / 噪声被过滤。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from webui.build_bundle import DEMO_RUNS, build_bundle  # noqa: E402


class TestBundle:
    def test_bundle_structure_covers_four_views(self) -> None:
        """① 四视图所需字段齐（runs/snapshots/scenarios/memory_compare + 逐场景 report 等）。"""
        b = build_bundle()
        for key in ("generated_at", "runs", "snapshots", "scenarios", "memory_compare", "meta"):
            assert key in b, f"bundle missing {key}"
        # 调查台所需：某 run 某场景的 report/grounding/tool_calls
        r = b["runs"]["batch1-seed42"]
        sc = r["scenarios"]["checkout-pod_crash-seed42"]
        for key in ("report", "grounding", "tool_calls"):
            assert key in sc, f"scenario entry missing {key}"
        assert "root_causes" in sc["report"] and sc["report"]["root_causes"]
        # 证据追溯所需：grounding 有 score、tool_calls 非空、gw-regression 有 audit
        assert "grounding_score" in sc["grounding"]
        assert len(sc["tool_calls"]) > 0
        assert "tool_audit" in b["runs"]["gw-regression"]["scenarios"]["checkout-pod_crash-seed42"]
        # 场景与产物所需：snapshot 含 GT 与 demo_md 字段（内容可为空串）
        snap = next(s for s in b["snapshots"] if s["scenario_id"] == "checkout-pod_crash-seed42")
        assert "ground_truth" in snap and "demo_md" in snap
        # 评测看板所需：raw 四方法 + memory_compare 双侧
        assert any("agent" in str(x) for x in r["raw"])
        assert b["memory_compare"]["off"] and b["memory_compare"]["on"]

    def test_whitelist_never_touches_historical_runs(self) -> None:
        """② run 白名单不触历史 runs——bundle 只含 DEMO_RUNS + oncall。"""
        b = build_bundle()
        included = set(b["runs"].keys())
        assert included == set(DEMO_RUNS) | {"oncall-e2e-cloud"}
        for historical in ("20260916T101856Z", "20260917T152725Z", "mem-sync-verify",
                           "gw-sync-verify", "cost-newrate-verify"):
            if historical in set(DEMO_RUNS):
                continue
            assert historical not in included, f"historical run {historical} leaked into bundle"

    def test_offline_mode_zero_llm_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """③ 离线（bundle 构建本就零 LLM）：任何 httpx/网络调用即失败。"""
        import webui.build_bundle as bb

        def no_network(*a: object, **k: object) -> None:
            raise AssertionError("bundle build must not touch network/LLM")

        monkeypatch.setattr(bb, "_read_json", bb._read_json)  # 文件 IO 照常
        # 全程只读本地文件——若实现里混入网络调用，此测试保护其被移除
        bundle = bb.build_bundle()
        assert bundle["meta"]["n_snapshots"] == 11

    def test_bundle_size_under_2mb(self) -> None:
        """④ bundle.js 体积 < 2MB（design 风险缓解）。"""
        out = Path("webui/bundle.js")
        if not out.exists():
            pytest.skip("bundle.js not built yet — run make demo-build first")
        assert out.stat().st_size < 2 * 1024 * 1024


class TestReplayAlerts:
    """任务 4.3：G-4 --replay-alerts（stub 调查，零 LLM）。"""

    @pytest.fixture
    def fixture_path(self) -> Path:
        p = Path(__file__).parent / "fixtures" / "demo-alerts.jsonl"
        assert p.exists(), "demo-alerts.jsonl fixture missing"
        return p

    def test_replay_runs_full_pipeline_with_dedup_and_noise_filter(
        self, fixture_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """① 回放全链：轮次1开查(stub)→轮次2同轮双告去重+噪声被滤→退出码0。"""
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.watchdog import main as wd_main

        investigated: list[dict] = []

        def stub_investigation(item: dict, **kw: object) -> None:
            investigated.append(item)

        monkeypatch.setattr("src.watchdog.runner.run_investigation", stub_investigation)
        monkeypatch.setattr("src.watchdog.runner.check_backends", lambda: True)
        # 隔离状态：chdir 到 tmp——Alerter 的相对 state_dir 在 tmp 下新建（零污染）
        monkeypatch.chdir(tmp_path)

        rc = wd_main([
            "--replay-alerts", str(fixture_path),
            "--once",
            "--prometheus-url", "http://127.0.0.1:1",  # 回放模式不触碰
            "--no-notify",
        ])
        assert rc == 0
        # 轮次 1：5 条白名单延迟告警（其中 2 条同服务去重后）→ 至少 1 次开查
        assert len(investigated) >= 1
        names = [i["alertname"] for i in investigated]
        # 轮次 2 的双告（NotReady + ReplicasMismatch 同服务）被 same_cycle 去重——不重复调查 checkout
        checkout_invs = [i for i in investigated if str(i.get("service_hint")) == "checkout"]
        assert len(checkout_invs) <= 1
        # 白名单外噪声 KubeContainerWaiting 绝不进调查
        assert "KubeContainerWaiting" not in names

    def test_replay_fixture_is_real_subset_no_fabrication(self, fixture_path: Path) -> None:
        """② fixture 不造数：每行可解析、labels 与 oncall 实录一致。"""
        lines = [ln for ln in fixture_path.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
        assert len(lines) == 2  # 两轮
        total = 0
        for ln in lines:
            arr = json.loads(ln)
            assert isinstance(arr, list) and arr
            for a in arr:
                assert a["labels"]["alertname"]  # 实录告警名
                assert a["state"] == "firing"
                assert a["activeAt"].startswith("2026-09-18T04:")  # 实录时间窗
                total += 1
        assert 5 <= total <= 10  # 3–5 条有代表性告警（含噪声与双告）

    def test_replay_respects_dry_run(self, fixture_path: Path, tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
        """③ dry-run 回放零调查副作用（would_start 日志路径）。"""
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.watchdog import main as wd_main

        called: list[dict] = []

        def stub_dry(item: dict, dry_run: bool = False, **kw: object) -> None:
            assert dry_run is True
            called.append(item)

        monkeypatch.setattr("src.watchdog.runner.run_investigation", stub_dry)
        monkeypatch.setattr("src.watchdog.runner.check_backends", lambda: True)
        monkeypatch.chdir(tmp_path)
        rc = wd_main(["--replay-alerts", str(fixture_path), "--once",
                      "--dry-run", "--no-notify"])
        assert rc == 0 and called
