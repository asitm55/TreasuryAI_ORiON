"""Instantiation and validation tests for models/financial.py."""

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
    KPIScore,
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

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 3)


# ---------------------------------------------------------------------------
# Instantiation — every model accepts valid data with no validation errors.
# ---------------------------------------------------------------------------


def test_cash_position_valid():
    pos = CashPosition(currency="USD", amount=Decimal("1250000.50"), account_id="ACC-001", as_of=NOW)
    assert pos.currency == "USD"
    assert pos.amount == Decimal("1250000.50")


def test_cash_flow_forecast_valid():
    fc = CashFlowForecast(
        entity="HoldCo",
        periods=[TODAY, date(2026, 9, 4)],
        inflows=[Decimal("100000"), Decimal("50000")],
        outflows=[Decimal("30000"), Decimal("20000")],
        net=[Decimal("70000"), Decimal("30000")],
    )
    assert len(fc.periods) == 2


def test_liquidity_metrics_valid():
    LiquidityMetrics(lcr=Decimal("1.42"), nsfr=Decimal("1.18"), hqla=Decimal("50000000"), net_outflows_30d=Decimal("35000000"))


def test_coverage_ratios_valid():
    CoverageRatios(lcr_ratio=Decimal("1.42"), nsfr_ratio=Decimal("1.18"), lcr_compliant=True, nsfr_compliant=True)


def test_liquidity_gap_valid():
    LiquidityGap(tenor_bucket="0-7d", gap_amount=Decimal("-500000"), cumulative_gap=Decimal("-500000"))


def test_fx_exposure_valid():
    FXExposure(
        currency_pair="EUR/USD",
        gross_long=Decimal("10000000"),
        gross_short=Decimal("3000000"),
        net=Decimal("7000000"),
        hedge_ratio=Decimal("0.65"),
    )


def test_var_metrics_valid():
    VaRMetrics(
        confidence=Decimal("0.95"),
        horizon_days=1,
        var_1d=Decimal("1200000"),
        var_10d=Decimal("3800000"),
        expected_shortfall=Decimal("1500000"),
    )


def test_rate_sensitivity_valid():
    RateSensitivity(dv01=Decimal("125000"), modified_duration=Decimal("4.2"), parallel_shift_impact=Decimal("-500000"))


def test_counterparty_risk_valid():
    CounterpartyRisk(counterparty_id="CP-001", gross_exposure=Decimal("2000000"), net_exposure=Decimal("1500000"), credit_rating="A-")


def test_risk_summary_valid():
    RiskSummary(total_fx_exposure=Decimal("7000000"), var_1d=Decimal("1200000"), top_risks=["EUR/USD exposure", "Counterparty CP-001"])


def test_working_capital_metrics_valid():
    WorkingCapitalMetrics(dso=Decimal("42.5"), dpo=Decimal("38.0"), ccc=Decimal("12.0"), days_cash_on_hand=Decimal("90"))


def test_kpi_scorecard_valid():
    KPIScorecard(metrics={"dpo": KPIScore(value=Decimal("38"), target=Decimal("45"), variance_pct=Decimal("-15.6"), on_target=False)})


def test_stress_test_result_valid():
    StressTestResult(scenario_name="liquidity_stress", lcr_post_stress=Decimal("1.074"), shortfall=Decimal("0"), severity=StressSeverity.HIGH)


def test_cash_anomaly_valid():
    CashAnomaly(entity="OpCo A", as_of=TODAY, expected_amount=Decimal("100000"), actual_amount=Decimal("250000"), z_score=Decimal("3.2"), description="Unexpected inflow spike")


def test_sweep_opportunity_valid():
    SweepOpportunity(from_account_id="ACC-002", to_account_id="ACC-001", currency="USD", amount=Decimal("500000"), rationale="Idle balance above target")


def test_scenario_result_valid():
    ScenarioResult(scenario_name="fx_shock", pnl_impact=Decimal("-820000"), description="EUR/USD -8% shock")


def test_trend_insight_valid():
    TrendInsight(metric_name="dso", direction=TrendDirection.UP, magnitude=Decimal("4.1"), commentary="DSO trending up over 3 periods")


def test_benchmark_result_valid():
    BenchmarkResult(metric_name="dso", entity_value=Decimal("42.5"), peer_median=Decimal("38.0"), percentile_rank=Decimal("65"), commentary="Above peer median")


def test_priority_issue_valid():
    PriorityIssue(issue="LCR near breach", category="liquidity", severity_score=Decimal("85"), recommended_owner="ATLAS")


def test_alert_event_valid():
    AlertEvent(rule_id="LIQ-001", metric="lcr", threshold=Decimal("1.10"), actual_value=Decimal("1.074"), severity=AlertSeverity.CRITICAL, message="LCR below 110%", timestamp=NOW)


def test_triage_request_valid():
    alert = AlertEvent(rule_id="LIQ-001", metric="lcr", threshold=Decimal("1.10"), actual_value=Decimal("1.074"), severity=AlertSeverity.CRITICAL, message="LCR below 110%", timestamp=NOW)
    TriageRequest(alert=alert, recommended_agent="ATLAS", note="Escalate for stress review")


# ---------------------------------------------------------------------------
# Validation — invalid data is rejected.
# ---------------------------------------------------------------------------


def test_cash_position_rejects_bad_currency():
    with pytest.raises(ValidationError):
        CashPosition(currency="US", amount=Decimal("100"), account_id="ACC-001", as_of=NOW)


def test_liquidity_metrics_rejects_negative_hqla():
    with pytest.raises(ValidationError):
        LiquidityMetrics(lcr=Decimal("1.1"), nsfr=Decimal("1.1"), hqla=Decimal("-1"), net_outflows_30d=Decimal("1000"))


def test_fx_exposure_rejects_hedge_ratio_above_one():
    with pytest.raises(ValidationError):
        FXExposure(currency_pair="EUR/USD", gross_long=Decimal("100"), gross_short=Decimal("50"), net=Decimal("50"), hedge_ratio=Decimal("1.5"))


def test_fx_exposure_rejects_malformed_currency_pair():
    with pytest.raises(ValidationError):
        FXExposure(currency_pair="EURUSD", gross_long=Decimal("100"), gross_short=Decimal("50"), net=Decimal("50"), hedge_ratio=Decimal("0.5"))


def test_var_metrics_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        VaRMetrics(confidence=Decimal("1.0"), horizon_days=1, var_1d=Decimal("100"), var_10d=Decimal("300"), expected_shortfall=Decimal("150"))


def test_var_metrics_rejects_zero_horizon():
    with pytest.raises(ValidationError):
        VaRMetrics(confidence=Decimal("0.95"), horizon_days=0, var_1d=Decimal("100"), var_10d=Decimal("300"), expected_shortfall=Decimal("150"))


def test_counterparty_risk_rejects_bad_credit_rating():
    with pytest.raises(ValidationError):
        CounterpartyRisk(counterparty_id="CP-001", gross_exposure=Decimal("100"), net_exposure=Decimal("80"), credit_rating="Z9")


def test_counterparty_risk_rejects_negative_gross_exposure():
    with pytest.raises(ValidationError):
        CounterpartyRisk(counterparty_id="CP-001", gross_exposure=Decimal("-1"), net_exposure=Decimal("80"), credit_rating="AA")


def test_cash_flow_forecast_rejects_mismatched_lengths():
    with pytest.raises(ValidationError):
        CashFlowForecast(
            entity="HoldCo",
            periods=[TODAY],
            inflows=[Decimal("100"), Decimal("200")],
            outflows=[Decimal("50")],
            net=[Decimal("50")],
        )


def test_stress_test_result_rejects_invalid_severity():
    with pytest.raises(ValidationError):
        StressTestResult(scenario_name="fx_shock", lcr_post_stress=Decimal("1.1"), shortfall=Decimal("0"), severity="SEVERE")


def test_benchmark_result_rejects_percentile_out_of_range():
    with pytest.raises(ValidationError):
        BenchmarkResult(metric_name="dso", entity_value=Decimal("42"), peer_median=Decimal("38"), percentile_rank=Decimal("150"), commentary="n/a")
