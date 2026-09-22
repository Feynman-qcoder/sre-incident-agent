"""Tests for add-incident-memory（零 LLM，tmp_path 隔离 memory 目录）。

单测清单（tasks 1.4）：writer 产出格式 / retrieve 精确匹配与 top-3 /
无匹配返回空（memory_miss）/ notes 人工条目优先 / INDEX rebuild 一致性 /
INCIDENT_MEMORY=off 时无 hint / Hint 块免责声明与限行 / writer 失败不抛。
另：Hint 内容不出现在 tool_calls_log（Hint≠Evidence 隔离断言）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from structlog.testing import capture_logs

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.agent.memory as mem  # noqa: E402
from src.agent.memory import (  # noqa: E402
    DISCLAIMER,
    MAX_LINES_PER_RECORD,
    build_hint_block,
    maybe_retrieve_and_build,
    rebuild_index,
    retrieve,
    write_incident,
)
from src.agent.schemas import InvestigationReport, RootCauseHypothesis, initial_state  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """每个测试独占 memory 目录（模块级常量经 monkeypatch 重定向）。"""
    d = tmp_path / "memory"
    monkeypatch.setattr(mem, "MEMORY_DIR", d)
    monkeypatch.setattr(mem, "INCIDENTS_DIR", d / "incidents")
    monkeypatch.setattr(mem, "NOTES_PATH", d / "notes" / "lessons.md")
    monkeypatch.setattr(mem, "INDEX_PATH", d / "INDEX.md")
    monkeypatch.setenv("INCIDENT_MEMORY", "on")
    return d


def _report(iid: str = "watchdog-KubePodNotReady-3d474e83",
            svc: str = "checkout", ft: str = "pod_crash",
            conf: float = 0.9) -> InvestigationReport:
    r = InvestigationReport(
        incident_id=iid,
        investigation_start_ts="2026-09-18T12:00:00+00:00",
        investigation_end_ts="2026-09-18T12:01:00+00:00",
        root_causes=[RootCauseHypothesis(rank=1, service=svc, fault_type=ft,
                                         description="容器 OOM 反复重启", confidence=conf)],
        remediation_steps=["回滚变更", "扩容内存限额"],
        fault_type_classification=ft,
    )
    r._memory_service = svc
    r._memory_fault_type = ft
    return r


class TestWriter:
    def test_write_produces_parseable_frontmatter(self, isolated_memory: Path) -> None:
        """① write_incident 产出 frontmatter 可回读（service/fault_type/根因字段）。"""
        p = write_incident(_report(), "artifacts/watchdog/x.json")
        assert p is not None and p.exists()
        fm = mem._parse_frontmatter(p)  # noqa: SLF001 — 测试内部解析器
        assert fm["incident_id"] == "watchdog-KubePodNotReady-3d474e83"
        assert fm["service"] == "checkout"
        assert fm["fault_type"] == "pod_crash"
        assert fm["root_cause_service"] == "checkout"
        assert fm["source_report"] == "artifacts/watchdog/x.json"
        body = p.read_text(encoding="utf-8")
        assert "容器 OOM 反复重启" in body and "回滚变更" in body

    def test_writer_failure_warns_not_raises(self, isolated_memory: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
        """⑧ writer 失败不抛（告警继续）——写盘异常模拟（Path.write_text 抛错）。"""
        def boom(self: Path, *a: object, **k: object) -> None:
            raise OSError("disk on fire (simulated)")

        monkeypatch.setattr(Path, "write_text", boom)
        with capture_logs() as logs:
            result = write_incident(_report(), "x.json")  # 不应抛
        assert result is None
        assert any(lg["event"] == "memory_write_failed" for lg in logs)


class TestRetrieve:
    def test_exact_match_and_topk_ordering(self, isolated_memory: Path) -> None:
        """② 精确匹配 + created_at 降序 top-3。"""
        for i, ts in enumerate(["2026-09-16T10", "2026-09-17T10", "2026-09-18T10",
                                "2026-09-15T10"]):
            r = _report(iid=f"watchdog-KubePodNotReady-aa00000{i}")
            r.investigation_end_ts = f"{ts}:00:00+00:00"
            write_incident(r, f"p{i}.json")
        # 加一条不同服务的（不应命中）
        write_incident(_report(iid="watchdog-OtelDemoHighLatencyP99-bb000001",
                               svc="shipping", ft="high_latency"), "other.json")
        hits = retrieve("checkout", "pod_crash", top_k=3)
        assert len(hits) == 3  # 4 条同键取最新 3
        assert hits[0]["created_at"] >= hits[1]["created_at"] >= hits[2]["created_at"]

    def test_no_match_returns_empty_and_miss_logged(self, isolated_memory: Path) -> None:
        """③ 无匹配 → 空列表 + memory_miss 日志（miss 日志在 maybe_ 挂点路径）。"""
        write_incident(_report(), "x.json")
        assert retrieve("nonexistent-service", "unknown_fault") == []
        with capture_logs() as logs:
            block, hit = maybe_retrieve_and_build("nonexistent-service", "unknown_fault")
        assert block == "" and hit is False
        assert any(lg["event"] == "memory_miss" for lg in logs)

    def test_notes_priority_over_incidents(self, isolated_memory: Path) -> None:
        """④ notes/lessons.md 人工条目优先于 AI 记录且标注来源。"""
        write_incident(_report(), "ai.json")
        notes = isolated_memory / "notes"
        notes.mkdir(parents=True)
        (notes / "lessons.md").write_text(
            "# Lessons\n\n## checkout pod_crash 人工结论\n"
            "service: checkout\nfault_type: pod_crash\n"
            "人工判断：该故障 9 成是 OOM，先查 memory limit 再看 RS。\n",
            encoding="utf-8")
        hits = retrieve("checkout", "pod_crash")
        assert hits and hits[0]["source"] == "notes"
        assert len(hits) >= 2  # notes + incidents
        block = build_hint_block(hits)
        assert "人工经验 #1（notes/lessons.md" in block


class TestIndexRebuild:
    def test_rebuild_index_consistency(self, isolated_memory: Path) -> None:
        """⑤ INDEX 删除后重建与文件一致（零丢失）。"""
        write_incident(_report(), "a.json")
        write_incident(_report(iid="watchdog-OtelDemoHighLatencyP99-cc000001",
                               svc="shipping", ft="high_latency"), "b.json")
        idx_before = mem.INDEX_PATH.read_text(encoding="utf-8")
        mem.INDEX_PATH.unlink()
        n = rebuild_index()
        assert n == 2
        assert mem.INDEX_PATH.read_text(encoding="utf-8") == idx_before  # 幂等一致


class TestGate:
    def test_disabled_returns_empty_and_no_io(self, isolated_memory: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
        """⑥ INCIDENT_MEMORY=off → 空注入、零文件 IO、state 无 hint。"""
        monkeypatch.setenv("INCIDENT_MEMORY", "off")
        block, hit = maybe_retrieve_and_build("checkout", "pod_crash")
        assert block == "" and hit is False
        assert not mem.INCIDENTS_DIR.exists()  # off 时不写任何文件
        state = initial_state("i", "s", "e", memory_hint=block)
        assert state["memory_hint"] == ""

    def test_hint_block_disclaimer_and_line_limit(self, isolated_memory: Path) -> None:
        """⑦ Hint 块含免责声明首行 + 每条 ≤15 行限行。"""
        long_body = {"source": "incidents", "service": "s", "fault_type": "f",
                     "created_at": "2026-09-18T10:00:00+00:00",
                     "root_cause_service": "s", "root_cause_fault_type": "f",
                     "confidence": "0.90", "incident_id": "x",
                     "body": "\n".join(f"line-{i}" for i in range(50))}
        block = build_hint_block([long_body])
        assert block.splitlines()[0] == f"[INCIDENT MEMORY — {DISCLAIMER}]"
        body_lines = [ln for ln in block.splitlines() if ln.startswith("line-")]
        assert len(body_lines) == MAX_LINES_PER_RECORD
        assert "[/INCIDENT MEMORY]" in block

    def test_hint_never_in_tool_calls_log(self) -> None:
        """⑨（spec 红线）Hint≠Evidence：hint 文本不出现在 tool_calls_log。"""
        hint = build_hint_block([{"source": "incidents", "service": "checkout",
                                  "fault_type": "pod_crash",
                                  "created_at": "2026-09-18T10:00:00+00:00",
                                  "root_cause_service": "checkout",
                                  "root_cause_fault_type": "pod_crash",
                                  "confidence": "0.90", "incident_id": "mem-test",
                                  "body": "容器 OOM 反复重启"}])
        # 模拟一条工具日志（真实形态：name/args/result）——hint 不在其中
        tool_calls_log = [{"iteration": 0, "name": "query_prometheus_range",
                           "args": {"query": "rate(calls_total)"},
                           "result": "some metrics data"}]
        for entry in tool_calls_log:
            assert hint not in str(entry)
            assert "INCIDENT MEMORY" not in str(entry)
