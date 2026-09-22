"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.datasources.replay import ReplayDataSource

FIXTURE_SNAPSHOT = Path(__file__).parent / "fixtures" / "snapshot-fixture"


@pytest.fixture(autouse=True)
def _isolate_incident_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 incident-memory 目录隔离到 tmp（autouse，防测试污染真实记忆库）。

    背景（2026-09-19 污染事故）：test_eval_all / test_demo_pack 的 stub 测试走
    run_scenario() → memory writer 触发（INCIDENT_MEMORY 默认 on、目录默认仓库根
    memory/）→ stub 报告按同 incident_id **覆盖**真实记忆（15 份被 "fixture stub
    hypothesis" 覆盖，靠 git checkout 恢复）。本 fixture 使所有测试的读写都落到
    tmp_path 下，根除该路径。

    实现注意：memory.py 的 MEMORY_DIR/INCIDENTS_DIR/NOTES_PATH/INDEX_PATH 均为
    **模块级常量（import 时求值）**——仅 setenv 无效（首版根修仅 setenv 时
    INDEX/checkout 仍被写，实证），必须同时 setattr 四个常量。
    """
    iso = tmp_path / "memory-isolated"
    monkeypatch.setenv("INCIDENT_MEMORY_DIR", str(iso))
    import src.agent.memory as mem
    monkeypatch.setattr(mem, "MEMORY_DIR", iso)
    monkeypatch.setattr(mem, "INCIDENTS_DIR", iso / "incidents")
    monkeypatch.setattr(mem, "NOTES_PATH", iso / "notes" / "lessons.md")
    monkeypatch.setattr(mem, "INDEX_PATH", iso / "INDEX.md")


@pytest.fixture
def replay_ds() -> ReplayDataSource:
    """ReplayDataSource backed by the minimal fixture snapshot."""
    return ReplayDataSource(FIXTURE_SNAPSHOT)


@pytest.fixture
def fixture_snapshot_dir() -> Path:
    return FIXTURE_SNAPSHOT
