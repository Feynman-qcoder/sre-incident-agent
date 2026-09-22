"""Offline unit tests for the alert watchdog (zero LLM, zero cluster, zero network).

fixture：tests/fixtures/alerts_live_20260916.json —— 2026-09-16 云端 Prometheus
/api/v1/alerts 实抓（25 条 kind 环境固有噪声，含 2 条 kube-system 的
KubePodCrashLooping），据此验证「环境固有噪声不触发调查」。
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha1
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from src.watchdog.alerter import Alerter
from src.watchdog.mapping import (
    fault_type_hint,
    map_alert,
    parse_prometheus_ts,
    service_from_pod,
)

FIXTURE = Path(__file__).parent / "fixtures" / "alerts_live_20260916.json"
FIXED_NOW = datetime(2026, 9, 16, 13, 0, 0, tzinfo=UTC)


@pytest.fixture
def noise_alerts() -> list[dict[str, object]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["alerts"]


@pytest.fixture
def alerter(tmp_path: Path) -> Alerter:
    return Alerter(state_dir=tmp_path / "watchdog", cooldown_min=45, max_per_hour=6)


def make_crash_alert(service: str = "checkout") -> dict[str, object]:
    """伪造一条 otel-demo <service> 的 KubePodCrashLooping firing 告警。

    pod 名用 Astronomy Shop 2.x 真实命名（无 otel-demo- 前缀，云端实测）。
    """
    return {
        "labels": {
            "alertname": "KubePodCrashLooping",
            "namespace": "otel-demo",
            "pod": f"{service}-abc12-xyz34",
            "container": service,
            "reason": "CrashLoopBackOff",
        },
        "annotations": {},
        "state": "firing",
        "activeAt": "2026-09-16T12:51:04.861992438Z",
        "value": "1e+00",
    }


# ── Requirement: 告警轮询与噪声过滤 ────────────────────────────────────────────


class TestNoiseFiltering:
    def test_fixture_is_all_environment_noise(self, noise_alerts: list[dict[str, object]]) -> None:
        """fixture 里没有任何 otel-demo namespace 的告警（全是环境噪声）。"""
        assert len(noise_alerts) >= 20  # 实抓 25 条，容忍后续微涨
        assert all(
            a["labels"].get("namespace") != "otel-demo"  # type: ignore[union-attr]
            for a in noise_alerts
        )

    def test_zero_pass_on_noise_fixture(self, alerter: Alerter,
                                        noise_alerts: list[dict[str, object]]) -> None:
        """场景「环境固有噪声不触发调查」：25 条噪声 → 0 条通过。"""
        passed = alerter.process(noise_alerts, now=FIXED_NOW)
        assert passed == []

    def test_every_noise_alert_logged_with_reason(
        self, alerter: Alerter, noise_alerts: list[dict[str, object]]
    ) -> None:
        """每条被忽略的告警都有 alert_filtered 日志，且原因合法。"""
        with capture_logs() as logs:
            alerter.process(noise_alerts, now=FIXED_NOW)
        filtered = [lg for lg in logs if lg["event"] == "alert_filtered"]
        assert len(filtered) == len(noise_alerts)
        reasons = {lg["reason"] for lg in filtered}
        # 2 条 kube-system 的 KubePodCrashLooping → wrong_namespace；其余 → not_in_whitelist
        assert reasons == {"not_in_whitelist", "wrong_namespace"}
        assert sum(1 for lg in filtered if lg["reason"] == "wrong_namespace") == 2


# ── Requirement: 白名单内的新告警通过 + 指纹 ───────────────────────────────────


class TestPassThrough:
    def test_fake_crash_passes_exactly_one(self, alerter: Alerter,
                                           noise_alerts: list[dict[str, object]]) -> None:
        """追加伪造 otel-demo checkout CrashLooping → 恰好 1 条通过、指纹正确。"""
        alerts = noise_alerts + [make_crash_alert("checkout")]
        passed = alerter.process(alerts, now=FIXED_NOW)
        assert len(passed) == 1

        item = passed[0]
        assert item["alertname"] == "KubePodCrashLooping"
        assert item["namespace"] == "otel-demo"
        assert item["service_hint"] == "checkout"
        assert item["fault_type_hint"] == "pod_crash"
        expected_fp = sha1(b"KubePodCrashLoopingotel-democheckout").hexdigest()[:8]
        assert item["fingerprint"] == expected_fp

        # 未 mark_investigated 前不进冷却表 → 重复轮询仍会 pass（冷却只在调查开始后生效）
        later = FIXED_NOW + timedelta(seconds=1)
        again = alerter.process([make_crash_alert("checkout")], now=later)
        assert len(again) == 1

    def test_alert_seen_logged_for_pass(self, alerter: Alerter) -> None:
        with capture_logs() as logs:
            alerter.process([make_crash_alert("cart")], now=FIXED_NOW)
        seen = [lg for lg in logs if lg["event"] == "alert_seen"]
        assert len(seen) == 1
        assert seen[0]["service"] == "cart"


# ── Requirement: 指纹去重与冷却 ────────────────────────────────────────────────


class TestCooldown:
    def test_second_poll_blocked_by_cooldown(self, alerter: Alerter) -> None:
        """场景「故障持续期间不重复调查」：同一指纹二次轮询被冷却拦截。"""
        passed1 = alerter.process([make_crash_alert("checkout")], now=FIXED_NOW)
        assert len(passed1) == 1
        alerter.mark_investigated(passed1[0], now=FIXED_NOW)

        with capture_logs() as logs:
            passed2 = alerter.process([make_crash_alert("checkout")], now=FIXED_NOW)
        assert passed2 == []
        skipped = [lg for lg in logs if lg["event"] == "skipped_cooldown"]
        assert len(skipped) == 1
        assert skipped[0]["fingerprint"] == passed1[0]["fingerprint"]
        assert skipped[0]["remaining_min"] >= 44  # 冷却 45 min 刚用掉 <1 min

    def test_cooldown_expires_after_window(self, alerter: Alerter) -> None:
        passed1 = alerter.process([make_crash_alert("checkout")], now=FIXED_NOW)
        alerter.mark_investigated(passed1[0], now=FIXED_NOW)
        later = FIXED_NOW + timedelta(minutes=46)
        assert len(alerter.process([make_crash_alert("checkout")], now=later)) == 1

    def test_state_survives_restart(self, tmp_path: Path) -> None:
        """state.json 落盘 → 新进程实例（重启模拟）冷却仍在。"""
        a1 = Alerter(state_dir=tmp_path / "wd")
        item = a1.process([make_crash_alert("checkout")], now=FIXED_NOW)[0]
        a1.mark_investigated(item, now=FIXED_NOW)

        a2 = Alerter(state_dir=tmp_path / "wd")  # 重新加载磁盘状态
        assert a2.process([make_crash_alert("checkout")], now=FIXED_NOW) == []

    def test_corrupt_state_rebuilds_empty(self, tmp_path: Path) -> None:
        """state.json 损坏 → 告警并重建空表，不崩溃（最坏代价：多跑一次调查）。"""
        d = tmp_path / "wd"
        d.mkdir(parents=True)
        (d / "state.json").write_text("{broken json !!", encoding="utf-8")

        with capture_logs() as logs:
            a = Alerter(state_dir=d)
        assert any(lg["event"] == "state_load_failed_rebuilding" for lg in logs)
        assert len(a.process([make_crash_alert("checkout")], now=FIXED_NOW)) == 1


# ── Requirement: 成本与并发护栏（每小时上限）──────────────────────────────────


class TestHourlyLimit:
    def test_hourly_budget_exhausted(self, tmp_path: Path) -> None:
        """max_per_hour=1 时：第 1 条通过，第 2 条被 hourly_limit_exceeded 过滤。"""
        a = Alerter(state_dir=tmp_path / "wd", max_per_hour=1)
        alerts = [make_crash_alert("checkout"), make_crash_alert("cart")]
        with capture_logs() as logs:
            passed = a.process(alerts, now=FIXED_NOW)
        assert len(passed) == 1
        limited = [lg for lg in logs if lg.get("reason") == "hourly_limit_exceeded"]
        assert len(limited) == 1

    def test_budget_counts_marked_investigations(self, tmp_path: Path) -> None:
        """已执行的调查占额度：本小时再来的新告警被拦。"""
        a = Alerter(state_dir=tmp_path / "wd", max_per_hour=1)
        item = a.process([make_crash_alert("checkout")], now=FIXED_NOW)[0]
        a.mark_investigated(item, now=FIXED_NOW)
        assert a.process([make_crash_alert("cart")], now=FIXED_NOW + timedelta(minutes=5)) == []


# ── mapping：纯函数映射（≥3 种告警名 + pod 名 → 服务名提取规则）──────────────


class TestMapping:
    @pytest.mark.parametrize("pod,expected", [
        # OTel Astronomy Shop 2.x 实际命名（无 otel-demo- 前缀，2026-09-16 云端实测）
        ("checkout-5df89485f4-572wp", "checkout"),
        ("product-catalog-7d8f9-10abc", "product-catalog"),   # 带连字符服务名
        ("load-generator-xyz99-11ab", "load-generator"),
        ("flagd-0", "flagd"),                                  # StatefulSet（ordinal）
        # 任务书/spec 模板命名（otel-demo- 前缀），兼容保留
        ("otel-demo-checkout-abc12-xyz34", "checkout"),
        ("otel-demo-product-catalog-7d8f9-10abc", "product-catalog"),
        ("otel-demo-flagd-0", "flagd"),
    ])
    def test_service_from_pod(self, pod: str, expected: str) -> None:
        assert service_from_pod(pod) == expected

    def test_service_from_pod_fallback_service_segment(self) -> None:
        """未知服务时回退启发式：取服务段（两种命名各自的服务段位置）。"""
        assert service_from_pod("unknownsvc-a1b2c-3d4e5", services=()) == "unknownsvc"
        assert service_from_pod("otel-demo-unknownsvc-a1b2c-3d4e5", services=()) == "unknownsvc"

    @pytest.mark.parametrize("alertname,labels,expected", [
        ("KubePodCrashLooping", {"reason": "CrashLoopBackOff"}, "pod_crash"),
        ("KubePodNotReady", {}, "pod_crash"),
        ("KubeStatefulSetReplicasMismatch", {}, "pod_crash"),
        ("KubePodCrashLooping", {"reason": "OOMKilled"}, "memory_stress"),
    ])
    def test_fault_type_hint(self, alertname: str, labels: dict[str, str],
                             expected: str) -> None:
        assert fault_type_hint(alertname, labels) == expected

    def test_parse_prometheus_nanosecond_ts(self) -> None:
        dt = parse_prometheus_ts("2026-09-16T12:51:04.861992438Z")
        assert dt is not None
        assert dt.microsecond == 861992  # 纳秒(438)截断，微秒保留前 6 位

    def test_window_is_active_at_minus_120s(self) -> None:
        item = map_alert(make_crash_alert("checkout"), now=FIXED_NOW)
        active = parse_prometheus_ts("2026-09-16T12:51:04.861992438Z")
        assert active is not None
        assert item["window_start"] == (active - timedelta(seconds=120)).isoformat()
        assert item["window_end"] == FIXED_NOW.isoformat()

    def test_missing_active_at_falls_back_to_now(self) -> None:
        alert = {"labels": {"alertname": "KubePodNotReady", "namespace": "otel-demo",
                            "pod": "otel-demo-cart-aaa11-bbb22"}, "state": "firing"}
        item = map_alert(alert, now=FIXED_NOW)
        assert item["window_start"] == (FIXED_NOW - timedelta(seconds=120)).isoformat()

    def test_deployment_label_wins_for_replicas_mismatch(self) -> None:
        """ReplicasMismatch 类告警无有效 pod 标签，deployment=服务名 优先（云端实测）。"""
        alert = {
            "labels": {"alertname": "KubeDeploymentReplicasMismatch", "namespace": "otel-demo",
                       "deployment": "checkout", "pod": "kube-state-metrics-7b49cdf8bb-h5rfm"},
            "state": "pending",
            "activeAt": "2026-09-16T12:51:04.861992438Z",
        }
        item = map_alert(alert, now=FIXED_NOW)
        assert item["service_hint"] == "checkout"
        assert item["fault_type_hint"] == "pod_crash"


# ── Requirement: dry-run 零成本演练（CLI 级）──────────────────────────────────


class TestDryRunCLI:
    def _sabotage_llm_imports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """若 dry-run 误入调查路径，对 agent 模块的 import 将直接失败。"""
        for mod in ("src.agent.graph", "src.agent.schemas", "src.datasources.live"):
            monkeypatch.setitem(sys.modules, mod, None)

    @staticmethod
    def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        """chdir 到临时目录：state.json 与报告目录均与真实 artifacts 隔离
        （云端 artifacts/watchdog 里可能已有 E2E 真实产物与冷却状态）。"""
        monkeypatch.chdir(tmp_path)
        return tmp_path / "artifacts" / "watchdog"

    def test_dry_run_on_noise_fixture_zero_investigations(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        noise_alerts: list[dict[str, object]]
    ) -> None:
        from scripts.watchdog import main

        self._sabotage_llm_imports(monkeypatch)
        wd_dir = self._isolated(monkeypatch, tmp_path)
        with capture_logs() as logs:
            rc = main(["--dry-run", "--once", "--alerts-file", str(FIXTURE)])
        assert rc == 0

        filtered = [lg for lg in logs if lg["event"] == "alert_filtered"]
        assert len(filtered) == len(noise_alerts)
        assert not [lg for lg in logs if lg["event"] == "investigation_started"]

        assert not wd_dir.exists()  # dry-run 零报告文件、零 state 写入

    def test_dry_run_with_actionable_alert_still_no_files(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """含可调查告警时 dry-run 打 would_start（含窗口与 incident_id），仍零落盘。"""
        from scripts.watchdog import main

        self._sabotage_llm_imports(monkeypatch)
        wd_dir = self._isolated(monkeypatch, tmp_path)
        alerts_file = tmp_path / "alerts_with_fault.json"
        alerts_file.write_text(
            json.dumps({"data": {"alerts": [make_crash_alert("checkout")]}}), encoding="utf-8"
        )
        with capture_logs() as logs:
            rc = main(["--dry-run", "--once", "--alerts-file", str(alerts_file)])
        assert rc == 0

        would = [lg for lg in logs if lg["event"] == "investigation_would_start"]
        assert len(would) == 1
        assert would[0]["incident_id"].startswith("watchdog-KubePodCrashLooping-")
        assert would[0]["window_start"] and would[0]["window_end"]
        assert not wd_dir.exists()  # dry-run 零报告文件、零 state 写入

    def test_help_outputs_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        from scripts.watchdog import main

        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        for flag in ("--once", "--interval", "--dry-run",
                     "--max-investigations-per-hour", "--cooldown-min",
                     "--service-cooldown-min"):
            assert flag in out


# ════════════════════════════════════════════════════════════════════════════
# P1: golden-signal alerts — service_name 解析、白名单 +2、服务级聚合冷却
# ════════════════════════════════════════════════════════════════════════════


def make_golden_alert(alertname: str, service: str) -> dict[str, object]:
    """伪造一条黄金指标告警（spanmetrics 规则静态注入 namespace，携带 service_name）。"""
    return {
        "labels": {
            "alertname": alertname,
            "namespace": "otel-demo",  # 规则 labels 静态注入（spanmetrics 无此标签）
            "service_name": service,
        },
        "annotations": {},
        "state": "pending",
        "activeAt": "2026-09-16T12:51:04.861992438Z",
        "value": "1.7",
    }


class TestGoldenAlertMapping:
    """Requirement: 黄金指标告警的服务解析与故障提示。"""

    def test_latency_alert_resolves_service_name(self) -> None:
        """service_name 合法 → 直接采用；hint = high_latency。"""
        item = map_alert(make_golden_alert("OtelDemoHighLatencyP99", "product-catalog"),
                         now=FIXED_NOW)
        assert item["service_hint"] == "product-catalog"
        assert item["fault_type_hint"] == "high_latency"
        assert item["namespace"] == "otel-demo"

    def test_error_alert_hint_is_http_abort(self) -> None:
        item = map_alert(make_golden_alert("OtelDemoHighErrorRate", "payment"), now=FIXED_NOW)
        assert item["service_hint"] == "payment"
        assert item["fault_type_hint"] == "http_abort"

    def test_telemetry_absent_hint_is_pod_crash(self) -> None:
        """批次1 010 补盲：absent 告警携带 service_name（子查询 by 保留）→ 照常 service_hint；
        hint = pod_crash（指标消失最常见根因是进程消失）。"""
        item = map_alert(make_golden_alert("OtelDemoTelemetryAbsent", "quote"), now=FIXED_NOW)
        assert item["service_hint"] == "quote"
        assert item["fault_type_hint"] == "pod_crash"

    def test_invalid_service_name_falls_back_to_pod(self) -> None:
        """service_name 非已知服务名 → 回退 pod 名解析（防脏数据）。"""
        alert = make_golden_alert("OtelDemoHighLatencyP99", "not-a-real-service")
        alert["labels"]["pod"] = "checkout-abc12-xyz34"  # type: ignore[index]
        item = map_alert(alert, now=FIXED_NOW)
        assert item["service_hint"] == "checkout"


class TestGoldenAlertWhitelist:
    """Requirement: 黄金指标告警通过过滤（白名单——批次1 后含 4 项 OtelDemo 规则）。"""

    def test_golden_alerts_pass_filter(self, alerter: Alerter) -> None:
        alerts = [
            make_golden_alert("OtelDemoHighLatencyP99", "product-catalog"),
            make_golden_alert("OtelDemoHighErrorRate", "payment"),
        ]
        with capture_logs() as logs:
            passed = alerter.process(alerts, now=FIXED_NOW)
        assert len(passed) == 2
        assert {str(p["service_hint"]) for p in passed} == {"product-catalog", "payment"}
        assert any(lg["event"] == "alert_seen" and lg.get("service") == "payment"
                   for lg in logs)

    def test_telemetry_absent_passes_filter(self, alerter: Alerter) -> None:
        """批次1：OtelDemoTelemetryAbsent 在白名单内（DEFAULT_WHITELIST 8 项）。"""
        from src.watchdog.alerter import DEFAULT_WHITELIST
        assert "OtelDemoTelemetryAbsent" in DEFAULT_WHITELIST
        passed = alerter.process(
            [make_golden_alert("OtelDemoTelemetryAbsent", "quote")], now=FIXED_NOW)
        assert len(passed) == 1
        assert passed[0]["service_hint"] == "quote"


class TestServiceAggregateCooldown:
    """Requirement: 指纹去重与冷却 — 服务级聚合（第二层）。"""

    def test_same_service_second_alertname_blocked(self, alerter: Alerter) -> None:
        """P0 实测场景：同一故障 3 告警名 → 服务聚合后仅首个触发调查。"""
        first = alerter.process(
            [make_crash_alert("checkout")], now=FIXED_NOW  # labels 带 pod=checkout-abc12-xyz34
        )
        assert len(first) == 1
        alerter.mark_investigated(first[0], now=FIXED_NOW)

        # 同服务不同告警名（KubePodNotReady，不同指纹）在服务冷却期内 → 被拦
        second_alert = {
            "labels": {"alertname": "KubePodNotReady", "namespace": "otel-demo",
                       "pod": "checkout-abc12-xyz34"},
            "state": "pending",
            "activeAt": "2026-09-16T12:51:04.861992438Z",
        }
        with capture_logs() as logs:
            passed = alerter.process([second_alert], now=FIXED_NOW + timedelta(minutes=1))
        assert passed == []
        skipped = [lg for lg in logs if lg["event"] == "skipped_service_cooldown"]
        assert len(skipped) == 1
        assert skipped[0]["service"] == "checkout"
        assert skipped[0]["first_alertname"] == "KubePodCrashLooping"

    def test_different_service_unaffected(self, alerter: Alerter) -> None:
        """cart 在冷却中，shipping 的告警正常通过（不跨服务误伤）。"""
        first = alerter.process([make_crash_alert("cart")], now=FIXED_NOW)
        alerter.mark_investigated(first[0], now=FIXED_NOW)
        passed = alerter.process([make_crash_alert("shipping")], now=FIXED_NOW)
        assert len(passed) == 1
        assert passed[0]["service_hint"] == "shipping"

    def test_service_cooldown_zero_disables_aggregation(self, tmp_path: Path) -> None:
        """--service-cooldown-min 0 → 关闭聚合，回退 P0 行为（不同指纹各查一次）。"""
        a = Alerter(state_dir=tmp_path / "wd", service_cooldown_min=0)
        first = a.process([make_crash_alert("checkout")], now=FIXED_NOW)
        a.mark_investigated(first[0], now=FIXED_NOW)
        second_alert = {
            "labels": {"alertname": "KubePodNotReady", "namespace": "otel-demo",
                       "pod": "checkout-abc12-xyz34"},
            "state": "pending",
            "activeAt": "2026-09-16T12:51:04.861992438Z",
        }
        passed = a.process([second_alert], now=FIXED_NOW + timedelta(minutes=1))
        assert len(passed) == 1  # 不同指纹、聚合关闭 → 放行

    def test_service_cooldown_expires(self, alerter: Alerter) -> None:
        """服务冷却过期后（46 min > 45 min），同服务新告警名可再次开查。"""
        first = alerter.process([make_crash_alert("checkout")], now=FIXED_NOW)
        alerter.mark_investigated(first[0], now=FIXED_NOW)
        later_alert = {
            "labels": {"alertname": "OtelDemoHighLatencyP99", "namespace": "otel-demo",
                       "service_name": "checkout"},
            "state": "pending",
            "activeAt": "2026-09-16T12:51:04.861992438Z",
        }
        passed = alerter.process([later_alert],
                                 now=FIXED_NOW + timedelta(minutes=46))
        assert len(passed) == 1

    def test_mark_investigated_writes_service_table(self, alerter: Alerter) -> None:
        """mark 后 state 的服务时间戳表 + 指纹表 + recent 均更新并落盘。"""
        item = alerter.process([make_crash_alert("checkout")], now=FIXED_NOW)[0]
        alerter.mark_investigated(item, now=FIXED_NOW)
        svc_table = alerter._state["service_last_investigated"]  # type: ignore[index]
        assert "checkout" in svc_table
        assert _iso(svc_table["checkout"]) == FIXED_NOW  # type: ignore[arg-type]

    def test_old_state_json_backward_compatible(self, tmp_path: Path) -> None:
        """P0 的 state.json（无 service_last_investigated 键）直接可读，行为正常。"""
        d = tmp_path / "wd"
        d.mkdir(parents=True)
        real_fp = Alerter.fingerprint("KubePodCrashLooping", "otel-demo", "checkout")
        old_state = {
            "fingerprints": {
                real_fp: {"alertname": "KubePodCrashLooping", "service": "checkout",
                          "last_investigated_at": FIXED_NOW.isoformat()},
            },
            "recent_investigations": [FIXED_NOW.isoformat()],
        }
        (d / "state.json").write_text(json.dumps(old_state), encoding="utf-8")
        a = Alerter(state_dir=d)  # 加载不炸
        # 旧指纹冷却仍在（指纹级去重兼容）
        assert a.process([make_crash_alert("checkout")], now=FIXED_NOW) == []
        # 服务聚合表从旧文件推不出 → 不同告警名不被服务级拦截（hourly 额度 2/6 未超）
        second_alert = {
            "labels": {"alertname": "KubePodNotReady", "namespace": "otel-demo",
                       "pod": "checkout-abc12-xyz34"},
            "state": "pending",
            "activeAt": "2026-09-16T12:51:04.861992438Z",
        }
        with capture_logs() as logs:
            passed = a.process([second_alert], now=FIXED_NOW + timedelta(minutes=1))
        assert len(passed) == 1  # 服务表为空 → 不拦
        assert not [lg for lg in logs if lg["event"] == "skipped_service_cooldown"]

    # ── P1.5（D-P1-01）：同轮 cycle-local 去重 ─────────────────────────────────

    def test_same_cycle_same_service_dedup(self, alerter: Alerter) -> None:
        """D-P1-01（E2E 001 实证）：同一轮内 2 条同服务不同告警名 → 仅首条 passed，
        第二条被 cycle-local 拦截（reason=same_cycle，first_alertname=首条告警名）。"""
        crash = make_crash_alert("checkout")  # KubePodCrashLooping, pod=checkout-abc12-xyz34
        not_ready = {
            "labels": {"alertname": "KubePodNotReady", "namespace": "otel-demo",
                       "pod": "checkout-abc12-xyz34"},
            "state": "pending",
            "activeAt": "2026-09-16T12:51:04.861992438Z",
        }
        with capture_logs() as logs:
            passed = alerter.process([crash, not_ready], now=FIXED_NOW)
        assert len(passed) == 1
        assert passed[0]["alertname"] == "KubePodCrashLooping"
        assert passed[0]["service_hint"] == "checkout"
        skipped = [lg for lg in logs if lg["event"] == "skipped_service_cooldown"]
        assert len(skipped) == 1
        assert skipped[0]["service"] == "checkout"
        assert skipped[0]["reason"] == "same_cycle"
        assert skipped[0]["first_alertname"] == "KubePodCrashLooping"

    def test_same_cycle_different_services_unaffected(self, alerter: Alerter) -> None:
        """同轮 2 条不同服务（checkout + shipping）→ 互不影响，均 passed（防误伤回归）。"""
        crash = make_crash_alert("checkout")
        golden = {
            "labels": {"alertname": "OtelDemoHighLatencyP99", "namespace": "otel-demo",
                       "service_name": "shipping"},
            "state": "pending",
            "activeAt": "2026-09-16T12:51:04.861992438Z",
        }
        with capture_logs() as logs:
            passed = alerter.process([crash, golden], now=FIXED_NOW)
        assert len(passed) == 2
        assert {str(p["service_hint"]) for p in passed} == {"checkout", "shipping"}
        assert not [lg for lg in logs if lg["event"] == "skipped_service_cooldown"]

    def test_same_cycle_zero_cooldown_keeps_pure_fingerprint(self, tmp_path: Path) -> None:
        """--service-cooldown-min 0 → cycle-local 拦截也关闭（同轮同服务不同指纹均放行）。"""
        a = Alerter(state_dir=tmp_path / "wd", service_cooldown_min=0)
        crash = make_crash_alert("checkout")
        not_ready = {
            "labels": {"alertname": "KubePodNotReady", "namespace": "otel-demo",
                       "pod": "checkout-abc12-xyz34"},
            "state": "pending",
            "activeAt": "2026-09-16T12:51:04.861992438Z",
        }
        with capture_logs() as logs:
            passed = a.process([crash, not_ready], now=FIXED_NOW)
        assert len(passed) == 2  # 聚合关闭 → 纯指纹行为，各查一次
        assert not [lg for lg in logs if lg["event"] == "skipped_service_cooldown"]


def _iso(ts: object) -> datetime:
    """Parse an ISO string back to datetime (test helper for state assertions)."""
    return datetime.fromisoformat(str(ts))
