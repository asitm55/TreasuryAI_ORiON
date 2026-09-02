"""Instantiation and validation tests for models/responses.py."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from models.financial import (
    AlertEvent,
    AlertSeverity,
    BenchmarkResult,
    CashAnomaly,
    CashFlowForecast,
    CashPosition,
    CounterpartyRisk,
    CoverageRatios,
    FXExposure,
    KPIScorecard,
    LiquidityGap,
    LiquidityMetrics,
    PriorityIssue,
    RateSensitivity,
    RiskSummary,
    ScenarioResult,
    StressSeverity,
    StressTestResult,
    SweepOpportunity,
    TrendDirection,
    TrendInsight,
    TriageRequest,
    VaRMetrics,
    WorkingCapitalMetrics,
)
from models.responses import (
    AgentResponse,
    AriaResponse,
    AtlasResponse,
    CoraResponse,
    FiraResponse,
    OrionResponse,
    Recommendation,
    ResponseStatus,
    TaraResponse,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 3)


def _recommendation(requires_approval: bool = True) -> Recommendation:
    return Recommendation(
        action="Increase HQLA buffer by $15M",
        rationale="LCR projected to fall below 110% under stress",
        estimated_impact="+8.2pp LCR",
        requires_approval=requires_approval,
    )


def test_recommendation_valid():
    _recommendation()


def test_agent_response_valid():
    resp = AgentResponse(agent_id="ATLAS", request_id="req-1", status=ResponseStatus.COMPLETE, reasoning="Checked LCR via calculate_lcr")
    assert resp.raw_llm_output is None


def test_agent_response_rejects_invalid_status():
    with pytest.raises(ValidationError):
        AgentResponse(agent_id="ATLAS", request_id="req-1", status="UNKNOWN", reasoning="n/a")


def test_atlas_response_valid():
    AtlasResponse(
        agent_id="ATLAS",
        request_id="req-1",
        status=ResponseStatus.PENDING_APPROVAL,
        reasoning="Stress test breaches near-term threshold",
        liquidity_metrics=LiquidityMetrics(lcr=Decimal("1.07"), nsfr=Decimal("1.05"), hqla=Decimal("40000000"), net_outflows_30d=Decimal("37000000")),
        coverage_ratios=CoverageRatios(lcr_ratio=Decimal("1.07"), nsfr_ratio=Decimal("1.05"), lcr_compliant=True, nsfr_compliant=True),
        gaps_identified=[LiquidityGap(tenor_bucket="0-7d", gap_amount=Decimal("-500000"), cumulative_gap=Decimal("-500000"))],
        recommendations=[_recommendation()],
        stress_results=StressTestResult(scenario_name="liquidity_stress", lcr_post_stress=Decimal("1.074"), shortfall=Decimal("0"), severity=StressSeverity.HIGH),
    )


def test_cora_response_valid():
    CoraResponse(
        agent_id="CORA",
        request_id="req-1",
        status=ResponseStatus.COMPLETE,
        reasoning="Reviewed 30d forecast and payment patterns",
        net_cash_position=CashPosition(currency="USD", amount=Decimal("24300000"), account_id="ACC-001", as_of=NOW),
        forecast_30d=CashFlowForecast(entity="HoldCo", periods=[TODAY], inflows=[Decimal("100000")], outflows=[Decimal("50000")], net=[Decimal("50000")]),
        working_capital=WorkingCapitalMetrics(dso=Decimal("42.5"), dpo=Decimal("38.0"), ccc=Decimal("12.0"), days_cash_on_hand=Decimal("90")),
        anomalies=[CashAnomaly(entity="OpCo A", as_of=TODAY, expected_amount=Decimal("100000"), actual_amount=Decimal("250000"), z_score=Decimal("3.2"), description="Inflow spike")],
        sweep_opportunities=[SweepOpportunity(from_account_id="ACC-002", to_account_id="ACC-001", currency="USD", amount=Decimal("500000"), rationale="Idle balance")],
        recommendations=[_recommendation(requires_approval=False)],
    )


def test_tara_response_valid():
    TaraResponse(
        agent_id="TARA",
        request_id="req-1",
        status=ResponseStatus.COMPLETE,
        reasoning="Computed FX exposure and VaR",
        risk_summary=RiskSummary(total_fx_exposure=Decimal("7000000"), var_1d=Decimal("1200000"), top_risks=["EUR/USD"]),
        fx_exposures=[FXExposure(currency_pair="EUR/USD", gross_long=Decimal("10000000"), gross_short=Decimal("3000000"), net=Decimal("7000000"), hedge_ratio=Decimal("0.65"))],
        var_metrics=VaRMetrics(confidence=Decimal("0.95"), horizon_days=1, var_1d=Decimal("1200000"), var_10d=Decimal("3800000"), expected_shortfall=Decimal("1500000")),
        rate_sensitivity=RateSensitivity(dv01=Decimal("125000"), modified_duration=Decimal("4.2"), parallel_shift_impact=Decimal("-500000")),
        counterparty_risks=[CounterpartyRisk(counterparty_id="CP-001", gross_exposure=Decimal("2000000"), net_exposure=Decimal("1500000"), credit_rating="A-")],
        scenario_results=[ScenarioResult(scenario_name="fx_shock", pnl_impact=Decimal("-820000"), description="EUR/USD -8%")],
        recommendations=[_recommendation()],
    )


def test_fira_response_valid():
    FiraResponse(
        agent_id="FIRA",
        request_id="req-1",
        status=ResponseStatus.COMPLETE,
        reasoning="Scored KPIs and benchmarked against peers",
        kpi_scorecard=KPIScorecard(metrics={}),
        trend_insights=[TrendInsight(metric_name="dso", direction=TrendDirection.UP, magnitude=Decimal("4.1"), commentary="Trending up")],
        benchmark_comparison=BenchmarkResult(metric_name="dso", entity_value=Decimal("42.5"), peer_median=Decimal("38.0"), percentile_rank=Decimal("65"), commentary="Above median"),
        executive_narrative="Treasury performance is broadly healthy this period.",
        priority_issues=[PriorityIssue(issue="LCR near breach", category="liquidity", severity_score=Decimal("85"), recommended_owner="ATLAS")],
    )


def test_aria_response_valid():
    alert = AlertEvent(rule_id="LIQ-001", metric="lcr", threshold=Decimal("1.10"), actual_value=Decimal("1.074"), severity=AlertSeverity.CRITICAL, message="LCR below 110%", timestamp=NOW)
    AriaResponse(
        agent_id="ARIA",
        request_id="req-1",
        status=ResponseStatus.COMPLETE,
        reasoning="Evaluated all alert rules against current snapshot",
        alerts=[alert],
        critical_count=1,
        high_count=0,
        triage_requests=[TriageRequest(alert=alert, recommended_agent="ATLAS", note="Escalate")],
    )


def test_orion_response_valid():
    OrionResponse(
        agent_id="ORION",
        request_id="req-1",
        status=ResponseStatus.PENDING_APPROVAL,
        reasoning="Synthesised ATLAS and TARA findings",
        session_id="sess-1",
        agents_invoked=["ATLAS", "TARA"],
        specialist_summaries={"ATLAS": "LCR at 107% under stress", "TARA": "EUR/USD exposure elevated"},
        final_briefing="Liquidity stress test shows LCR approaching the regulatory minimum.",
        recommendations=[_recommendation()],
        approval_required=True,
    )
