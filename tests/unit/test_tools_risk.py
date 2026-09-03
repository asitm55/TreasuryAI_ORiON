"""Tests for tools/risk.py."""

import dataclasses
from datetime import date
from decimal import Decimal

import pytest

from core.tool_registry import ToolError
from data.synthetic_loader import FXShockAssumption, SyntheticDataLoader
from tools.risk import (
    calculate_counterparty_exposure,
    calculate_duration,
    calculate_fx_exposure,
    calculate_hedge_effectiveness,
    calculate_interest_rate_sensitivity,
    calculate_var,
    run_scenario_analysis,
)


@pytest.fixture(scope="module")
def base_case():
    return SyntheticDataLoader().load_scenario("base_case")


@pytest.fixture(scope="module")
def fx_shock():
    return SyntheticDataLoader().load_scenario("fx_shock")


# --- calculate_fx_exposure -----------------------------------------------------


def test_calculate_fx_exposure_computes_net_and_hedge_ratio(fx_shock):
    exposures = {e.currency_pair: e for e in calculate_fx_exposure(fx_shock)}
    eur_usd = exposures["EUR/USD"]
    assert eur_usd.gross_long == Decimal("12000000")
    assert eur_usd.net == Decimal("12000000")
    assert eur_usd.hedge_ratio == Decimal("0")  # fully unhedged in fx_shock

    usd_chf = exposures["USD/CHF"]
    assert usd_chf.hedge_ratio == Decimal("1")  # fully hedged


def test_calculate_fx_exposure_short_position_gives_negative_net(fx_shock):
    exposures = {e.currency_pair: e for e in calculate_fx_exposure(fx_shock)}
    usd_jpy = exposures["USD/JPY"]
    assert usd_jpy.gross_short == Decimal("15000000")
    assert usd_jpy.net == Decimal("-15000000")


def test_calculate_fx_exposure_rejects_empty_book(base_case):
    empty_snapshot = dataclasses.replace(base_case, fx_positions=())
    with pytest.raises(ToolError):
        calculate_fx_exposure(empty_snapshot)


# --- calculate_var --------------------------------------------------------------


def test_calculate_var_1d_matches_hand_computed_percentile():
    returns = [Decimal(str(x)) for x in [-80000, -50000, -20000, -10000, 5000, 10000, 15000, 20000, 25000, 30000]]
    result = calculate_var(returns, Decimal("0.95"), 1)
    # 10 obs, (1-0.95)*10 = 0.5 -> tail_index 0 -> worst observation, -(-80000)=80000
    assert result.var_1d == Decimal("80000")
    assert result.expected_shortfall == Decimal("80000")
    assert result.var_10d > result.var_1d  # sqrt(10) scaling


def test_calculate_var_rejects_short_series():
    with pytest.raises(ToolError):
        calculate_var([Decimal("1")], Decimal("0.95"), 1)


def test_calculate_var_rejects_confidence_out_of_range():
    with pytest.raises(ToolError):
        calculate_var([Decimal("1"), Decimal("2")], Decimal("1.0"), 1)
    with pytest.raises(ToolError):
        calculate_var([Decimal("1"), Decimal("2")], Decimal("0"), 1)


def test_calculate_var_rejects_non_positive_horizon():
    with pytest.raises(ToolError):
        calculate_var([Decimal("1"), Decimal("2")], Decimal("0.95"), 0)


# --- calculate_duration ----------------------------------------------------------


def test_calculate_duration_positive_and_reasonable():
    cash_flows = [(Decimal("1"), Decimal("50000")), (Decimal("2"), Decimal("50000")), (Decimal("3"), Decimal("1050000"))]
    rates = [Decimal("0.04"), Decimal("0.042"), Decimal("0.045")]
    result = calculate_duration(cash_flows, rates)
    assert result.present_value > 0
    # Duration for a 3y bond with most cash flow at maturity should be close to 3y.
    assert Decimal("2.5") < result.macaulay_duration <= Decimal("3.0")
    assert result.dv01 > 0


def test_calculate_duration_rejects_empty_cash_flows():
    with pytest.raises(ToolError):
        calculate_duration([], [])


def test_calculate_duration_rejects_mismatched_lengths():
    with pytest.raises(ToolError):
        calculate_duration([(Decimal("1"), Decimal("100"))], [])


def test_calculate_duration_rejects_negative_time():
    with pytest.raises(ToolError):
        calculate_duration([(Decimal("-1"), Decimal("100"))], [Decimal("0.04")])


def test_calculate_duration_rejects_zero_total_present_value():
    with pytest.raises(ToolError):
        calculate_duration([(Decimal("1"), Decimal("0"))], [Decimal("0.04")])


# --- calculate_hedge_effectiveness ------------------------------------------------


def test_calculate_hedge_effectiveness_highly_effective():
    result = calculate_hedge_effectiveness(Decimal("9000000"), Decimal("1000000"))
    assert result.classification == "HIGHLY_EFFECTIVE"
    assert result.hedge_ratio == Decimal("0.9")


def test_calculate_hedge_effectiveness_partially_effective():
    result = calculate_hedge_effectiveness(Decimal("6000000"), Decimal("4000000"))
    assert result.classification == "PARTIALLY_EFFECTIVE"


def test_calculate_hedge_effectiveness_ineffective():
    result = calculate_hedge_effectiveness(Decimal("1000000"), Decimal("9000000"))
    assert result.classification == "INEFFECTIVE"


def test_calculate_hedge_effectiveness_rejects_negative_inputs():
    with pytest.raises(ToolError):
        calculate_hedge_effectiveness(Decimal("-1"), Decimal("100"))


def test_calculate_hedge_effectiveness_rejects_both_zero():
    with pytest.raises(ToolError):
        calculate_hedge_effectiveness(Decimal("0"), Decimal("0"))


# --- run_scenario_analysis --------------------------------------------------------


def test_run_scenario_analysis_uses_snapshot_shocks_by_default(fx_shock):
    results = run_scenario_analysis(fx_shock)
    by_name_prefix = {r.scenario_name.split()[0]: r for r in results}
    eur_usd_result = by_name_prefix["EUR/USD"]
    assert eur_usd_result.pnl_impact == Decimal("12000000") * Decimal("-0.08")


def test_run_scenario_analysis_accepts_explicit_params(fx_shock):
    custom = [FXShockAssumption(currency_pair="USD/CHF", shock_pct=Decimal("0.10"))]
    results = run_scenario_analysis(fx_shock, scenario_params=custom)
    assert len(results) == 1
    assert results[0].pnl_impact == Decimal("1000000") * Decimal("0.10")


def test_run_scenario_analysis_rejects_no_shocks(base_case):
    with pytest.raises(ToolError):
        run_scenario_analysis(base_case)  # base_case.scenario_shocks == ()


# --- calculate_counterparty_exposure -----------------------------------------------


def test_calculate_counterparty_exposure_splits_multi_currency_counterparty(base_case):
    exposures = calculate_counterparty_exposure(base_case)
    cp002_rows = [e for e in exposures if e.counterparty_id == "CP-002"]
    assert {e.currency for e in cp002_rows} == {"USD", "JPY"}
    jpy_row = next(e for e in cp002_rows if e.currency == "JPY")
    assert jpy_row.gross_exposure == Decimal("199500000")


def test_calculate_counterparty_exposure_rejects_no_counterparties(base_case):
    empty_snapshot = dataclasses.replace(base_case, counterparties=())
    with pytest.raises(ToolError):
        calculate_counterparty_exposure(empty_snapshot)


# --- calculate_interest_rate_sensitivity --------------------------------------------


def test_calculate_interest_rate_sensitivity_positive_dv01(base_case):
    result = calculate_interest_rate_sensitivity(
        list(base_case.investment_positions), 100, as_of=date(2026, 9, 3)
    )
    assert result.dv01 > 0
    assert result.modified_duration > 0
    assert result.parallel_shift_impact < 0  # rates up -> value down


def test_calculate_interest_rate_sensitivity_negative_shock_gives_positive_impact(base_case):
    result = calculate_interest_rate_sensitivity(
        list(base_case.investment_positions), -100, as_of=date(2026, 9, 3)
    )
    assert result.parallel_shift_impact > 0  # rates down -> value up


def test_calculate_interest_rate_sensitivity_rejects_empty_portfolio():
    with pytest.raises(ToolError):
        calculate_interest_rate_sensitivity([], 100)


def test_calculate_interest_rate_sensitivity_rejects_all_matured_positions(base_case):
    far_future = date(2035, 1, 1)
    with pytest.raises(ToolError):
        calculate_interest_rate_sensitivity(list(base_case.investment_positions), 100, as_of=far_future)
