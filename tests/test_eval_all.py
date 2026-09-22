"""Tests for fix-eval-cross-run: --mode all 同 run 四方法 + compare 防呆（零 LLM）。

Agent 段经 monkeypatch 注入假 build_graph（返回 fixture 数据可判的报告）；
baseline 走真实实现（纯计算），断言与 baselines-only 模式数值一致（确定性）。
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.scenario_runner import run_scenario  # noqa: E402
from src.agent.schemas import InvestigationReport, RootCauseHypothesis  # noqa: E402

FIXTURE_SNAPSHOT = Path(__file__).parent / "fixtures" / "snapshot-fixture"
FOUR_METHODS = {"agent", "random", "zscore", "composite_zscore"}


def _fake_report(scenario_id: str) -> InvestigationReport:
    """可判分的最小报告：top-1 = checkout/pod_crash（fixture 的 ground truth）。"""
    return InvestigationReport(
        incident_id=scenario_id,
        investigation_start_ts="2026-09-16T12:00:00+00:00",
        investigation_end_ts="2026-09-16T12:02:00+00:00",
        root_causes=[
            RootCauseHypothesis(
                rank=1,
                service="checkout",
                fault_type="pod_crash",
                description="fixture stub hypothesis",
                confidence=0.9,
            ),
        ],
        remediation_steps=[],
        fault_type_classification="pod_crash",
        latency_s=1.0,
        cost_usd=0.001,
    )


@pytest.fixture
def stub_agent(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """用假 graph 替换 build_graph（零 LLM）；记录传入的 ds 实例。"""
    import src.agent.graph as graph_mod

    seen_ds: list[object] = []

    class _FakeGraph:
        def invoke(self, state: dict) -> dict:  # noqa: ANN001
            return {
                "final_report": _fake_report(str(state.get("incident_id", "x"))),
                "tool_calls_log": [],
            }

    def fake_build_graph(ds: object, audit_path: object = None) -> _FakeGraph:
        seen_ds.append(ds)
        return _FakeGraph()

    monkeypatch.setattr(graph_mod, "build_graph", fake_build_graph)
    return seen_ds


class TestModeAll:
    def test_returns_four_methods(
        self, stub_agent: list[object], tmp_path: Path
    ) -> None:
        """① --mode all 返回同时含 agent/random/zscore/composite_zscore 四键。"""
        result = run_scenario(FIXTURE_SNAPSHOT, mode="all", run_id="")
        assert set(result) == FOUR_METHODS
        # agent 键为 per-scenario dict 且数值来自注入的假报告
        assert result["agent"]["predicted_service"] == "checkout"  # type: ignore[index]
        # 基线键同样为 per-scenario dict
        for m in ("random", "zscore", "composite_zscore"):
            assert isinstance(result[m], dict)  # type: ignore[index]

    def test_same_datasource_instance(
        self, stub_agent: list[object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """② D2 同一性：快照只加载一次，agent 与 baselines 消费同一 ds 实例。"""
        import src.datasources.replay as replay_mod

        created: list[object] = []
        real_cls = replay_mod.ReplayDataSource

        class _RecordingDS(real_cls):  # type: ignore[misc, valid-type]
            def __init__(self, snapshot_dir: Path) -> None:
                super().__init__(snapshot_dir)
                created.append(self)

        monkeypatch.setattr(replay_mod, "ReplayDataSource", _RecordingDS)
        result = run_scenario(FIXTURE_SNAPSHOT, mode="all", run_id="")

        assert len(created) == 1, "all 模式必须只构造一次 ReplayDataSource（D2）"
        assert stub_agent and stub_agent[0] is created[0]
        assert set(result) == FOUR_METHODS

    def test_baselines_match_baselines_only(
        self, stub_agent: list[object], tmp_path: Path
    ) -> None:
        """③ 同 seed 同快照 → 三基线数值与 baselines-only 模式完全一致（确定性）。"""
        all_result = run_scenario(FIXTURE_SNAPSHOT, mode="all", run_id="")
        only_result = run_scenario(FIXTURE_SNAPSHOT, mode="baselines-only", run_id="")
        for m in ("random", "zscore", "composite_zscore"):
            assert all_result[m] == only_result[m], f"baseline {m} not reproducible"  # type: ignore[index]


class TestCompareMissingHint:
    def test_prints_hint_for_incomplete_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """④ compare 对缺失方法的 run 打印提示（防呆，非硬失败）。"""
        monkeypatch.chdir(tmp_path)
        artifacts = tmp_path / "artifacts" / "fakeagentonly"
        artifacts.mkdir(parents=True)
        # 仅含 agent 的历史 run 形态
        (artifacts / "raw_results.json").write_text(
            json.dumps([
                {
                    "snapshot_dir": "snapshots/x",
                    "agent": {"accuracy_at_1": 1, "accuracy_at_3": 1, "mrr": 1.0,
                              "fault_type_correct": 1, "grounding_score": 1.0,
                              "latency_s": 10.0, "cost_usd": 0.001},
                }
            ]),
            encoding="utf-8",
        )

        from eval import compare

        monkeypatch.setattr(sys, "argv", ["compare", "--run-id", "fakeagentonly"])
        with contextlib.suppress(SystemExit):
            compare.main()
        out = capsys.readouterr().out
        assert "缺失 3 个方法" in out
        assert "make eval-all" in out
