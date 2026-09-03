"""Tests for tools/liquidity.py."""

from decimal import Decimal

import pytest

from core.tool_registry import ToolError
from data.synthetic_loader import InvestmentPosition, SyntheticDataLoader
from tools.liquidity import (
    calculate_concentration_risk,
    calculate_lcr,
    calculate_liquidity_gap,
    calculate_nsfr,
    get_cash_position,
    get_investment_portfolio,
    run_liquidity_stress,
)


@pytest.fixture(scope="module")
def base_case():
    return SyntheticDataLoader().load_scenario("base_case")


@pytest.fixture(scope="module")
def liquidity_stress():
    return SyntheticDataLoader().load_scenario("liquidity_stress")


# --- calculate_lcr ----------------------------------------------------------


def test_calculate_lcr_matches_scenario(base_case):
    result = calculate_lcr(base_case.hqla, base_case.net_cash_outflows_30d)
    assert result.ratio == Decimal("1.4")
    assert result.compliant is True


def test_calculate_lcr_below_100_percent_is_not_compliant():
    result = calculate_lcr(Decimal("50"), Decimal("100"))
    assert result.compliant is False


def test_calculate_lcr_rejects_negative_hqla():
    with pytest.raises(ToolError):
        calculate_lcr(Decimal("-1"), Decimal("100"))


def test_calculate_lcr_rejects_zero_or_negative_outflows():
    with pytest.raises(ToolError):
        calculate_lcr(Decimal("100"), Decimal("0"))
    with pytest.raises(ToolError):
        calculate_lcr(Decimal("100"), Decimal("-5"))


# --- calculate_nsfr ----------------------------------------------------------


def test_calculate_nsfr_matches_scenario(base_case):
    result = calculate_nsfr(base_case.available_stable_funding, base_case.required_stable_funding)
    assert result.compliant is True
    assert round(result.ratio, 4) == Decimal("1.1869")


def test_calculate_nsfr_rejects_negative_asf():
    with pytest.raises(ToolError):
        calculate_nsfr(Decimal("-1"), Decimal("100"))


def test_calculate_nsfr_rejects_zero_or_negative_rsf():
    with pytest.raises(ToolError):
        calculate_nsfr(Decimal("100"), Decimal("0"))


# --- calculate_liquidity_gap -------------------------------------------------


def test_calculate_liquidity_gap_accumulates_in_order():
    gaps = calculate_liquidity_gap({"0-7d": Decimal("-500000"), "8-30d": Decimal("200000"), "31-90d": Decimal("100000")})
    assert [g.tenor_bucket for g in gaps] == ["0-7d", "8-30d", "31-90d"]
    assert gaps[0].cumulative_gap == Decimal("-500000")
    assert gaps[1].cumulative_gap == Decimal("-300000")
    assert gaps[2].cumulative_gap == Decimal("-200000")


def test_calculate_liquidity_gap_rejects_empty_input():
    with pytest.raises(ToolError):
        calculate_liquidity_gap({})


# --- get_cash_position --------------------------------------------------------


def test_get_cash_position_flattens_all_entities(base_case):
    positions = get_cash_position(base_case)
    assert len(positions) == sum(len(v) for v in base_case.cash_positions.values())
    account_ids = {p.account_id for p in positions}
    assert "HOLD-USD-01" in account_ids
    assert "OPB-JPY-01" in account_ids


# --- get_investment_portfolio --------------------------------------------------


def test_get_investment_portfolio_breaks_totals_out_by_currency(base_case):
    portfolio = get_investment_portfolio(base_case)
    assert len(portfolio.positions) == 10
    assert portfolio.total_market_value_by_currency["USD"] > 0
    assert portfolio.total_market_value_by_currency["JPY"] > 0
    # HQLA-eligible USD value should be less than total USD value (some USD
    # positions in base_case are not HQLA-eligible corporate bonds).
    assert portfolio.hqla_eligible_value_by_currency["USD"] < portfolio.total_market_value_by_currency["USD"]


def test_get_investment_portfolio_rejects_empty_snapshot(base_case):
    import dataclasses

    empty_snapshot = dataclasses.replace(base_case, investment_positions=())
    with pytest.raises(ToolError):
        get_investment_portfolio(empty_snapshot)


# --- run_liquidity_stress -------------------------------------------------------


def test_run_liquidity_stress_matches_hand_built_liquidity_stress_scenario(base_case, liquidity_stress):
    result = run_liquidity_stress(base_case, Decimal("0.30"))
    expected_lcr = liquidity_stress.hqla / liquidity_stress.net_cash_outflows_30d
    assert result.lcr_post_stress == expected_lcr
    assert result.severity.value == "HIGH"


def test_run_liquidity_stress_zero_shock_matches_base_lcr(base_case):
    result = run_liquidity_stress(base_case, Decimal("0"))
    assert result.lcr_post_stress == Decimal("1.4")
    assert result.severity.value == "LOW"


def test_run_liquidity_stress_severe_shock_is_critical(base_case):
    result = run_liquidity_stress(base_case, Decimal("2.0"))  # outflows triple
    assert result.lcr_post_stress < Decimal("1.0")
    assert result.severity.value == "CRITICAL"
    assert result.shortfall > 0


def test_run_liquidity_stress_rejects_shock_at_or_below_negative_one(base_case):
    with pytest.raises(ToolError):
        run_liquidity_stress(base_case, Decimal("-1"))


def test_run_liquidity_stress_medium_severity_band(base_case):
    result = run_liquidity_stress(base_case, Decimal("0.22"))
    assert Decimal("1.10") <= result.lcr_post_stress < Decimal("1.20")
    assert result.severity.value == "MEDIUM"


def test_run_liquidity_stress_rejects_zero_outflows(base_case):
    import dataclasses

    zero_outflow_snapshot = dataclasses.replace(base_case, net_cash_outflows_30d=Decimal("0"))
    with pytest.raises(ToolError):
        run_liquidity_stress(zero_outflow_snapshot, Decimal("0"))


# --- calculate_concentration_risk -----------------------------------------------


def test_calculate_concentration_risk_breaks_out_by_currency(base_case):
    result = calculate_concentration_risk(list(base_case.investment_positions))
    currencies = {c.currency for c in result.by_currency}
    assert currencies == {"USD", "EUR", "GBP", "JPY", "CHF"}
    usd = next(c for c in result.by_currency if c.currency == "USD")
    assert usd.largest_counterparty_id == "CP-001"
    assert result.exceeds_threshold is True  # single-position currencies are 100% concentrated


def test_calculate_concentration_risk_below_threshold_when_evenly_split():
    positions = [
        InvestmentPosition(
            instrument_id=f"INV-{i}", entity="HoldCo", instrument_type="Bond", currency="USD",
            face_value=Decimal("1000000"), market_value=Decimal("1000000"),
            maturity_date="2027-01-01", coupon_rate=Decimal("0.03"),
            counterparty_id=f"CP-{i}", hqla_eligible=True,
        )
        for i in range(4)
    ]
    result = calculate_concentration_risk(positions)
    usd = result.by_currency[0]
    assert usd.largest_concentration_pct == Decimal("0.25")
    assert usd.exceeds_threshold is False  # exactly at threshold, not above


def test_calculate_concentration_risk_rejects_empty_positions():
    with pytest.raises(ToolError):
        calculate_concentration_risk([])


def test_calculate_concentration_risk_rejects_zero_market_value_currency():
    positions = [
        InvestmentPosition(
            instrument_id="INV-1", entity="HoldCo", instrument_type="Bond", currency="USD",
            face_value=Decimal("0"), market_value=Decimal("0"),
            maturity_date="2027-01-01", coupon_rate=Decimal("0.03"),
            counterparty_id="CP-1", hqla_eligible=True,
        )
    ]
    with pytest.raises(ToolError):
        calculate_concentration_risk(positions)
