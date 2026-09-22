"""Tests for evaluation harness: metrics, grounding verifier, baselines."""

from __future__ import annotations

from src.agent.schemas import EvidenceItem, InvestigationReport, RootCauseHypothesis
from src.datasources.replay import ReplayDataSource

# ── Grounding verifier tests ───────────────────────────────────────────────────

class TestGroundingVerifier:
    def _make_report_with_evidence(self, query_or_id: str, signal_type: str = "metric") -> InvestigationReport:
        return InvestigationReport(
            incident_id="test",
            investigation_start_ts="2024-01-15T14:00:00Z",
            investigation_end_ts="2024-01-15T14:05:00Z",
            root_causes=[
                RootCauseHypothesis(
                    rank=1,
                    service="checkoutservice",
                    fault_type="pod_crash",
                    description="test",
                    confidence=0.9,
                    evidence=[
                        EvidenceItem(
                            signal_type=signal_type,
                            query_or_id=query_or_id,
                            observed_value="error_rate=0.95",
                        )
                    ],
                )
            ],
            fault_type_classification="pod_crash",
        )

    def test_verified_evidence_scores_1(self) -> None:
        from eval.grounding_verifier import verify
        query = 'sum(rate(http_server_request_duration_seconds_count{service_name="checkoutservice"}[2m]))'
        report = self._make_report_with_evidence(query, "metric")
        tool_log = [{"tool_name": "query_prometheus_range", "args": {"query": query},
                     "query_or_id": [query], "result_preview": "mean=0.95"}]
        result = verify(report, tool_log)
        assert result.grounding_score == 1.0
        assert not result.has_hallucination_warning

    def test_hallucinated_evidence_scores_0(self) -> None:
        from eval.grounding_verifier import verify
        report = self._make_report_with_evidence("completely_fabricated_query_xyz_123", "metric")
        tool_log = [{"tool_name": "query_prometheus_range",
                     "args": {"query": 'up{job="real"}'},
                     "query_or_id": ['up{job="real"}'],
                     "result_preview": "up=1"}]
        result = verify(report, tool_log)
        assert result.grounding_score == 0.0
        assert result.has_hallucination_warning
        assert len(result.failed_items) == 1

    def test_no_evidence_scores_1(self) -> None:
        from eval.grounding_verifier import verify
        report = InvestigationReport(
            incident_id="test",
            investigation_start_ts="2024-01-15T14:00:00Z",
            investigation_end_ts="2024-01-15T14:05:00Z",
            root_causes=[
                RootCauseHypothesis(
                    rank=1, service="svc", fault_type="pod_crash",
                    description="x", confidence=0.5, evidence=[],
                )
            ],
            fault_type_classification="pod_crash",
        )
        result = verify(report, [])
        assert result.grounding_score == 1.0
        assert not result.has_hallucination_warning

    def test_partial_grounding(self) -> None:
        from eval.grounding_verifier import verify
        real_query = 'sum(rate(error_count{service="checkoutservice"}[2m]))'
        fake_query = "totally_made_up_metric_abc_xyz_123"
        report = InvestigationReport(
            incident_id="test",
            investigation_start_ts="2024-01-15T14:00:00Z",
            investigation_end_ts="2024-01-15T14:05:00Z",
            root_causes=[
                RootCauseHypothesis(
                    rank=1, service="checkoutservice", fault_type="pod_crash",
                    description="x", confidence=0.9,
                    evidence=[
                        EvidenceItem(signal_type="metric", query_or_id=real_query,
                                     observed_value="high"),
                        EvidenceItem(signal_type="metric", query_or_id=fake_query,
                                     observed_value="high"),
                    ],
                )
            ],
            fault_type_classification="pod_crash",
        )
        tool_log = [{"tool_name": "query_prometheus_range",
                     "args": {"query": real_query},
                     "query_or_id": [real_query], "result_preview": "..."}]
        result = verify(report, tool_log)
        assert result.grounding_score == 0.5
        assert result.verified_count == 1
        assert result.total_count == 2


# ── Metrics tests ──────────────────────────────────────────────────────────────

class TestMetrics:
    def _make_sr(self, pred_service: str, pred_fault: str, rank: int = 1,
                  gt_service: str = "checkoutservice", gt_fault: str = "pod_crash",
                  grounding: float = 1.0) -> object:
        from eval.metrics import ScenarioResult
        report = InvestigationReport(
            incident_id="test",
            investigation_start_ts="2024-01-15T14:00:00Z",
            investigation_end_ts="2024-01-15T14:05:00Z",
            root_causes=[
                RootCauseHypothesis(
                    rank=1, service=pred_service, fault_type=pred_fault,
                    description="x", confidence=0.9,
                )
            ],
            fault_type_classification=pred_fault,
        )
        return ScenarioResult(
            scenario_id="test",
            report=report,
            ground_truth={"fault_service": gt_service, "fault_type": gt_fault},
            grounding_score=grounding,
        )

    def test_perfect_prediction(self) -> None:
        from eval.metrics import compute_metrics
        sr = self._make_sr("checkoutservice", "pod_crash")
        metrics = compute_metrics([sr])  # type: ignore[list-item]
        assert metrics.accuracy_at_1 == 1.0
        assert metrics.accuracy_at_3 == 1.0
        assert metrics.mrr == 1.0
        assert metrics.fault_type_accuracy == 1.0

    def test_wrong_prediction(self) -> None:
        from eval.metrics import compute_metrics
        sr = self._make_sr("frontend", "high_latency")
        metrics = compute_metrics([sr])  # type: ignore[list-item]
        assert metrics.accuracy_at_1 == 0.0
        assert metrics.accuracy_at_3 == 0.0
        assert metrics.mrr == 0.0
        assert metrics.fault_type_accuracy == 0.0

    def test_correct_service_wrong_fault_type(self) -> None:
        from eval.metrics import compute_metrics
        sr = self._make_sr("checkoutservice", "high_latency")  # correct service, wrong fault
        metrics = compute_metrics([sr])  # type: ignore[list-item]
        assert metrics.accuracy_at_1 == 0.0   # both must match
        assert metrics.fault_type_accuracy == 0.0

    def test_empty_results(self) -> None:
        from eval.metrics import compute_metrics
        metrics = compute_metrics([])
        assert metrics.n_scenarios == 0
        assert metrics.accuracy_at_1 == 0.0

    def test_mrr_rank_2(self) -> None:
        from eval.metrics import ScenarioResult, compute_metrics
        report = InvestigationReport(
            incident_id="test",
            investigation_start_ts="2024-01-15T14:00:00Z",
            investigation_end_ts="2024-01-15T14:05:00Z",
            root_causes=[
                RootCauseHypothesis(rank=1, service="frontend", fault_type="high_latency",
                                    description="x", confidence=0.8),
                RootCauseHypothesis(rank=2, service="checkoutservice", fault_type="pod_crash",
                                    description="correct", confidence=0.7),
            ],
            fault_type_classification="high_latency",
        )
        sr = ScenarioResult(
            scenario_id="test",
            report=report,
            ground_truth={"fault_service": "checkoutservice", "fault_type": "pod_crash"},
            grounding_score=1.0,
        )
        metrics = compute_metrics([sr])
        assert metrics.accuracy_at_1 == 0.0    # rank-1 is wrong
        assert metrics.accuracy_at_3 == 1.0    # rank-2 is correct
        assert abs(metrics.mrr - 0.5) < 1e-9   # 1/2


# ── Baseline tests ─────────────────────────────────────────────────────────────

class TestRandomBaseline:
    def test_produces_valid_report(self, replay_ds: ReplayDataSource) -> None:
        from eval.baselines.random_baseline import RandomBaseline
        baseline = RandomBaseline(seed=42)
        report = baseline.predict(
            replay_ds, "2024-01-15T13:59:00+00:00", "2024-01-15T14:06:00+00:00",
            "otel-demo", "test-scenario",
        )
        assert len(report.root_causes) == 3
        assert report.root_causes[0].rank == 1
        assert report.root_causes[0].service  # non-empty

    def test_deterministic_with_seed(self, replay_ds: ReplayDataSource) -> None:
        from eval.baselines.random_baseline import RandomBaseline
        b1 = RandomBaseline(seed=42)
        b2 = RandomBaseline(seed=42)
        r1 = b1.predict(replay_ds, "2024-01-15T13:59:00+00:00",
                        "2024-01-15T14:06:00+00:00", "otel-demo", "test")
        r2 = b2.predict(replay_ds, "2024-01-15T13:59:00+00:00",
                        "2024-01-15T14:06:00+00:00", "otel-demo", "test")
        assert r1.root_causes[0].service == r2.root_causes[0].service


class TestZScoreBaseline:
    def test_produces_valid_report(self, replay_ds: ReplayDataSource) -> None:
        from eval.baselines.zscore_baseline import ZScoreBaseline
        baseline = ZScoreBaseline()
        report = baseline.predict(
            replay_ds, "2024-01-15T13:59:00+00:00", "2024-01-15T14:06:00+00:00",
            "otel-demo", "test-scenario",
        )
        assert len(report.root_causes) <= 3
        assert report.fault_type_classification == "high_latency"

    def test_identifies_anomalous_service(self, replay_ds: ReplayDataSource) -> None:
        from eval.baselines.zscore_baseline import ZScoreBaseline
        baseline = ZScoreBaseline()
        report = baseline.predict(
            replay_ds, "2024-01-15T13:59:00+00:00", "2024-01-15T14:06:00+00:00",
            "otel-demo", "test-scenario",
        )
        # Fixture has checkout with a high error_rate during the fault window
        top_services = [rc.service for rc in report.root_causes]
        assert "checkout" in top_services


class TestCompositeZScoreBaseline:
    def test_produces_valid_report(self, replay_ds: ReplayDataSource) -> None:
        from eval.baselines.composite_zscore import CompositeZScoreBaseline
        baseline = CompositeZScoreBaseline()
        report = baseline.predict(
            replay_ds, "2024-01-15T13:59:00+00:00", "2024-01-15T14:06:00+00:00",
            "otel-demo", "test-scenario",
        )
        assert len(report.root_causes) <= 3
        assert report.fault_type_classification in [
            "pod_crash", "high_latency", "cpu_stress", "memory_stress", "http_abort"
        ]
