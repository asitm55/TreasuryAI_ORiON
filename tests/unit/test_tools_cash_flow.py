"""Tests for tools/cash_flow.py."""

import dataclasses
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from core.tool_registry import ToolError
from data.synthetic_loader import SyntheticDataLoader
from models.financial import CashPosition
from tools.cash_flow import (
    analyse_payment_patterns,
    calculate_forecast_variance,
    calculate_net_cash_position,
    calculate_sweep_opportunity,
    calculate_working_capital_metrics,
    detect_anomalies,
    get_cash_flow_forecast,
)


@pytest.fixture(scope="module")
def base_case():
    return SyntheticDataLoader().load_scenario("base_case")


# --- get_cash_flow_forecast --------------------------------------------------


def test_get_cash_flow_forecast_covers_30_day_window(base_case):
    forecast = get_cash_flow_forecast(base_case, 30)
    assert forecast.entity == "Consolidated (USD)"
    assert len(forecast.periods) > 0
    assert all(p.month in (9, 10) for p in forecast.periods)
    for i, p in enumerate(forecast.periods):
        assert forecast.net[i] == forecast.inflows[i] - forecast.outflows[i]


def test_get_cash_flow_forecast_shorter_horizon_has_fewer_or_equal_periods(base_case):
    full = get_cash_flow_forecast(base_case, 30)
    short = get_cash_flow_forecast(base_case, 5)
    assert len(short.periods) <= len(full.periods)


def test_get_cash_flow_forecast_rejects_non_positive_horizon(base_case):
    with pytest.raises(ToolError):
        get_cash_flow_forecast(base_case, 0)
    with pytest.raises(ToolError):
        get_cash_flow_forecast(base_case, -5)


# --- calculate_net_cash_position ----------------------------------------------


def test_calculate_net_cash_position_sums_usd_only(base_case):
    pos = calculate_net_cash_position(base_case)
    assert pos.currency == "USD"
    expected = sum(
        p.amount
        for positions in base_case.cash_positions.values()
        for p in positions
        if p.currency == "USD"
    )
    assert pos.amount == expected


def test_calculate_net_cash_position_rejects_snapshot_with_no_usd_cash(base_case):
    stripped_positions = {
        entity: tuple(p for p in positions if p.currency != "USD")
        for entity, positions in base_case.cash_positions.items()
    }
    no_usd_snapshot = dataclasses.replace(base_case, cash_positions=stripped_positions)
    with pytest.raises(ToolError):
        calculate_net_cash_position(no_usd_snapshot)


# --- analyse_payment_patterns --------------------------------------------------


def test_analyse_payment_patterns_defaults_to_usd(base_case):
    result = analyse_payment_patterns(base_case)
    assert result.currency == "USD"
    assert result.net == result.total_inflows - result.total_outflows
    assert result.inflow_count + result.outflow_count > 0


def test_analyse_payment_patterns_other_currency(base_case):
    result = analyse_payment_patterns(base_case, currency="JPY")
    assert result.currency == "JPY"
    assert result.outflow_count >= 1


def test_analyse_payment_patterns_rejects_currency_with_no_entries(base_case):
    with pytest.raises(ToolError):
        analyse_payment_patterns(base_case, currency="AUD")


# --- calculate_working_capital_metrics -----------------------------------------


def test_calculate_working_capital_metrics_matches_hand_computed_values(base_case):
    result = calculate_working_capital_metrics(base_case)
    assert round(result.dso, 2) == Decimal("48.67")
    assert round(result.dpo, 2) == Decimal("40.56")
    assert result.ccc == result.dso - result.dpo
    assert result.days_cash_on_hand > 0


def test_calculate_working_capital_metrics_rejects_zero_revenue(base_case):
    broken = dataclasses.replace(base_case, annual_revenue=Decimal("0"))
    with pytest.raises(ToolError):
        calculate_working_capital_metrics(broken)


def test_calculate_working_capital_metrics_rejects_zero_cogs(base_case):
    broken = dataclasses.replace(base_case, annual_cogs=Decimal("0"))
    with pytest.raises(ToolError):
        calculate_working_capital_metrics(broken)


# --- detect_anomalies ----------------------------------------------------------


def test_detect_anomalies_flags_the_outlier():
    series = [
        (date(2026, 9, 1), Decimal("100000")),
        (date(2026, 9, 2), Decimal("105000")),
        (date(2026, 9, 3), Decimal("98000")),
        (date(2026, 9, 4), Decimal("500000")),
    ]
    anomalies = detect_anomalies("HoldCo", series, Decimal("1.0"))
    assert len(anomalies) == 1
    assert anomalies[0].actual_amount == Decimal("500000")


def test_detect_anomalies_no_anomalies_when_series_is_flat():
    series = [(date(2026, 9, i), Decimal("100000")) for i in range(1, 5)]
    assert detect_anomalies("HoldCo", series, Decimal("1.0")) == []


def test_detect_anomalies_rejects_short_series():
    with pytest.raises(ToolError):
        detect_anomalies("HoldCo", [(date(2026, 9, 1), Decimal("100"))], Decimal("2"))


def test_detect_anomalies_rejects_non_positive_threshold():
    series = [(date(2026, 9, 1), Decimal("100")), (date(2026, 9, 2), Decimal("200"))]
    with pytest.raises(ToolError):
        detect_anomalies("HoldCo", series, Decimal("0"))


# --- calculate_sweep_opportunity ------------------------------------------------


def _pos(account_id: str, amount: str, currency: str = "USD") -> CashPosition:
    return CashPosition(currency=currency, amount=Decimal(amount), account_id=account_id, as_of=datetime.now(timezone.utc))


def test_calculate_sweep_opportunity_identifies_idle_balance():
    positions = [_pos("A1", "2000000"), _pos("A2", "600000"), _pos("A3", "100000")]
    opportunities = calculate_sweep_opportunity(positions)
    assert len(opportunities) == 1
    opp = opportunities[0]
    assert opp.from_account_id == "A2"
    assert opp.to_account_id == "A1"
    assert opp.amount == Decimal("100000")


def test_calculate_sweep_opportunity_no_opportunity_when_single_account_per_currency():
    assert calculate_sweep_opportunity([_pos("A1", "2000000")]) == []


def test_calculate_sweep_opportunity_none_below_buffer():
    positions = [_pos("A1", "600000"), _pos("A2", "400000")]
    assert calculate_sweep_opportunity(positions) == []


def test_calculate_sweep_opportunity_rejects_empty_positions():
    with pytest.raises(ToolError):
        calculate_sweep_opportunity([])


# --- calculate_forecast_variance ------------------------------------------------


def test_calculate_forecast_variance_computes_errors():
    result = calculate_forecast_variance([Decimal("100"), Decimal("200")], [Decimal("90"), Decimal("220")])
    assert result.total_actual == Decimal("300")
    assert result.total_forecast == Decimal("310")
    assert result.mean_absolute_error == Decimal("15")


def test_calculate_forecast_variance_rejects_empty_series():
    with pytest.raises(ToolError):
        calculate_forecast_variance([], [])


def test_calculate_forecast_variance_rejects_mismatched_lengths():
    with pytest.raises(ToolError):
        calculate_forecast_variance([Decimal("1")], [Decimal("1"), Decimal("2")])


def test_calculate_forecast_variance_handles_zero_actual_without_div_by_zero():
    result = calculate_forecast_variance([Decimal("0"), Decimal("100")], [Decimal("10"), Decimal("90")])
    assert result.mean_absolute_error == Decimal("10")
