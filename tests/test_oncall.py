"""Tests for add-oncall-loop: notifier + ack CLI（零 LLM、零真实 webhook）。

本地 HTTP stub（threading + http.server）替代企微端点；凭据脱敏断言：
任何日志事件的字段值不得包含 URL 明文。
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pytest import CaptureFixture
from structlog.testing import capture_logs

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.watchdog_ack import main as ack_main  # noqa: E402
from src.agent.schemas import InvestigationReport, RootCauseHypothesis  # noqa: E402
from src.watchdog.notifier import build_markdown, notify_investigation  # noqa: E402


class _StubServer:
    """极简企微端点 stub：捕获请求体；可配置响应码与 errcode。"""

    def __init__(self, status: int = 200, errcode: int = 0) -> None:
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                outer.requests.append(json.loads(body))
                payload = {"errcode": errcode, "errmsg": "ok" if errcode == 0 else "fail"}
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/webhook/send"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> _StubServer:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


def _report(incident_id: str = "watchdog-KubePodNotReady-3d474e83",
            steps: list[str] | None = None) -> InvestigationReport:
    return InvestigationReport(
        incident_id=incident_id,
        investigation_start_ts="2026-09-18T12:00:00+00:00",
        investigation_end_ts="2026-09-18T12:01:00+00:00",
        root_causes=[
            RootCauseHypothesis(rank=1, service="checkout", fault_type="pod_crash",
                                description="容器因 OOM 反复重启\n第二行细节",
                                confidence=0.87),
        ],
        remediation_steps=steps if steps is not None else ["回滚触发重启的变更", "扩容内存限额"],
        fault_type_classification="pod_crash",
        latency_s=30.0,
        cost_usd=0.003,
    )


class TestBuildMarkdown:
    def test_contains_required_fields(self) -> None:
        """① 消息含 incident_id/告警/服务/top-1(服务+类型+置信度)/摘要/建议/路径/ack 指引。"""
        md = build_markdown(
            incident_id="watchdog-KubePodNotReady-3d474e83",
            alertname="KubePodNotReady", service="checkout",
            top_service="checkout", top_fault_type="pod_crash",
            top_confidence=0.87, root_cause_summary="容器因 OOM 反复重启",
            remediation_steps=["回滚变更", "扩容内存"],
            report_path="artifacts/watchdog/x.json",
        )
        for needle in ("watchdog-KubePodNotReady-3d474e83", "KubePodNotReady", "checkout",
                       "pod_crash", "87%", "容器因 OOM 反复重启", "回滚变更",
                       "artifacts/watchdog/x.json", "watchdog_ack --incident-id"):
            assert needle in md, f"missing: {needle}"

    def test_remediation_truncated_to_three(self) -> None:
        """② 修复建议截断至前 3 条。"""
        md = build_markdown(
            incident_id="i", alertname="a", service="s",
            top_service="s", top_fault_type="pod_crash", top_confidence=0.5,
            root_cause_summary="r", remediation_steps=["s1", "s2", "s3", "s4", "s5"],
            report_path="p.json",
        )
        assert "s3" in md and "s4" not in md and "s5" not in md


class TestNotifySend:
    def test_success_posts_wecom_payload_and_sent_event(self) -> None:
        """③ stub 200/errcode=0 → 企微 markdown payload 结构正确 + notification_sent。"""
        with _StubServer() as stub, capture_logs() as logs:
            ok = notify_investigation(_report(), "artifacts/watchdog/x.json",
                                      alertname="KubePodNotReady", service="checkout",
                                      webhook_url=stub.url)
        assert ok is True
        assert len(stub.requests) == 1
        body = stub.requests[0]
        assert body["msgtype"] == "markdown"
        assert "markdown" in body and "content" in body["markdown"]
        sent = [lg for lg in logs if lg["event"] == "notification_sent"]
        assert len(sent) == 1 and sent[0]["webhook_host"].startswith("127.0.0.1")

    def test_failure_degrades_not_raises(self) -> None:
        """④ stub 500 → 不抛、返回 False、notification_failed 事件、无 sent。"""
        with _StubServer(status=500) as stub, capture_logs() as logs:
            ok = notify_investigation(_report(), "p.json",
                                      alertname="KubePodNotReady", service="checkout",
                                      webhook_url=stub.url)
        assert ok is False
        failed = [lg for lg in logs if lg["event"] == "notification_failed"]
        assert len(failed) == 1
        assert not [lg for lg in logs if lg["event"] == "notification_sent"]

    def test_no_webhook_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """⑤ env 未配置且无覆盖 → notification_disabled，零 HTTP。"""
        monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)
        with capture_logs() as logs:
            ok = notify_investigation(_report(), "p.json",
                                      alertname="KubePodNotReady", service="checkout",
                                      webhook_url=None)
        assert ok is False
        disabled = [lg for lg in logs if lg["event"] == "notification_disabled"]
        assert len(disabled) == 1 and "not set" in disabled[0]["reason"]

    def test_logs_never_contain_url(self) -> None:
        """⑥ 日志脱敏：notification_* 事件的字段值不含 URL 明文（URL 即凭据）。"""
        with _StubServer() as stub, capture_logs() as logs:
            notify_investigation(_report(), "p.json",
                                 alertname="KubePodNotReady", service="checkout",
                                 webhook_url=stub.url)
        for lg in logs:
            if lg["event"].startswith("notification"):
                for v in lg.values():
                    assert "http://" not in str(v), f"URL leaked in {lg['event']}: {v}"
                    assert "https://" not in str(v), f"URL leaked in {lg['event']}: {v}"


class TestAckCli:
    @pytest.fixture
    def report_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """tmp artifacts/watchdog：一份报告 JSON + chdir（ack CLI 用相对路径）。"""
        d = tmp_path / "artifacts" / "watchdog"
        d.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        report = _report().model_dump()
        (d / "20260918T120000Z_KubePodNotReady_checkout.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")
        return d

    def test_ack_appends_and_rewrites(
        self, report_dir: Path, capsys: CaptureFixture[str]
    ) -> None:
        """⑦ ack → ack_log 追加 1 条 + 报告回写 acknowledged_at/by。"""
        rc = ack_main(["--incident-id", "watchdog-KubePodNotReady-3d474e83", "--by", "demo"])
        assert rc == 0
        ack_log = json.loads((report_dir / "ack_log.json").read_text(encoding="utf-8"))
        assert len(ack_log) == 1
        assert ack_log[0]["acknowledged_by"] == "demo"
        report = json.loads(
            (report_dir / "20260918T120000Z_KubePodNotReady_checkout.json")
            .read_text(encoding="utf-8"))
        assert report["acknowledged_by"] == "demo"
        assert "acknowledged_at" in report
        assert "已确认" in capsys.readouterr().out

    def test_repeated_ack_appends_history(self, report_dir: Path) -> None:
        """⑧ 重复 ack 幂等（追加式）：ack_log 两条历史，最新在后。"""
        ack_main(["--incident-id", "watchdog-KubePodNotReady-3d474e83", "--by", "alice"])
        ack_main(["--incident-id", "watchdog-KubePodNotReady-3d474e83",
                  "--by", "bob", "--note", "second look"])
        ack_log = json.loads((report_dir / "ack_log.json").read_text(encoding="utf-8"))
        assert len(ack_log) == 2
        assert ack_log[-1]["acknowledged_by"] == "bob"  # 最新在后

    def test_list_output_format(
        self, report_dir: Path, capsys: CaptureFixture[str]
    ) -> None:
        """⑨ --list：未确认 ⬜ → ack 后 ✅（含确认人）。"""
        ack_main(["--list"])
        out1 = capsys.readouterr().out
        assert "watchdog-KubePodNotReady-3d474e83" in out1
        assert "⬜" in out1 and "未确认 1" in out1

        ack_main(["--incident-id", "watchdog-KubePodNotReady-3d474e83", "--by", "demo"])
        ack_main(["--list"])
        out2 = capsys.readouterr().out
        assert "✅" in out2 and "demo" in out2 and "未确认 0" in out2
