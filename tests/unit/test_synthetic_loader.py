"""Tests for data/synthetic_loader.py."""

from decimal import Decimal

import pytest
import yaml

from data.synthetic_loader import (
    CashFlowDirection,
    FXDirection,
    ScenarioNotFoundError,
    SyntheticDataError,
    SyntheticDataLoader,
    TreasurySnapshot,
)
from models.financial import CashPosition

EXPECTED_SCENARIOS = {"base_case", "liquidity_stress", "fx_shock"}


@pytest.fixture(scope="module")
def loader() -> SyntheticDataLoader:
    return SyntheticDataLoader()


def test_list_scenarios_finds_all_three(loader):
    assert set(loader.list_scenarios()) == EXPECTED_SCENARIOS


@pytest.mark.parametrize("scenario_name", sorted(EXPECTED_SCENARIOS))
def test_load_scenario_populates_snapshot(loader, scenario_name):
    snap = loader.load_scenario(scenario_name)

    assert isinstance(snap, TreasurySnapshot)
    assert snap.scenario_name == scenario_name
    assert snap.entities == ("HoldCo", "OpCo A", "OpCo B")
    assert set(snap.currencies) == {"USD", "EUR", "GBP", "JPY", "CHF"}

    assert set(snap.cash_positions.keys()) == set(snap.entities)
    for positions in snap.cash_positions.values():
        assert len(positions) > 0
        assert all(isinstance(p, CashPosition) for p in positions)

    assert len(snap.investment_positions) == 10
    assert len(snap.counterparties) == 5
    assert len(snap.fx_positions) > 0
    assert len(snap.payment_schedule) > 0
    assert len(snap.rate_curve) > 0

    assert isinstance(snap.hqla, Decimal)
    assert isinstance(snap.net_cash_outflows_30d, Decimal)
    assert isinstance(snap.available_stable_funding, Decimal)
    assert isinstance(snap.required_stable_funding, Decimal)


def test_liquidity_stress_lcr_is_lower_than_base_case(loader):
    base = loader.load_scenario("base_case")
    stress = loader.load_scenario("liquidity_stress")

    base_lcr = base.hqla / base.net_cash_outflows_30d
    stress_lcr = stress.hqla / stress.net_cash_outflows_30d

    assert stress_lcr < base_lcr
    assert stress_lcr > Decimal("1.0")  # still Basel-compliant, just near the minimum
    assert base_lcr == Decimal("1.4")


def test_liquidity_stress_nsfr_unchanged_from_base_case(loader):
    base = loader.load_scenario("base_case")
    stress = loader.load_scenario("liquidity_stress")

    base_nsfr = base.available_stable_funding / base.required_stable_funding
    stress_nsfr = stress.available_stable_funding / stress.required_stable_funding

    assert base_nsfr == stress_nsfr


def test_fx_shock_has_unhedged_eur_usd_exposure_above_10m(loader):
    snap = loader.load_scenario("fx_shock")
    unhedged_eur_usd = sum(
        p.notional for p in snap.fx_positions
        if p.currency_pair == "EUR/USD" and not p.hedge_designated
    )
    assert unhedged_eur_usd > Decimal("10000000")


def test_fx_shock_declares_scenario_shocks(loader):
    snap = loader.load_scenario("fx_shock")
    pairs = {s.currency_pair: s.shock_pct for s in snap.scenario_shocks}
    assert pairs["EUR/USD"] == Decimal("-0.08")
    assert pairs["GBP/USD"] == Decimal("-0.05")


def test_base_case_and_liquidity_stress_have_no_scenario_shocks(loader):
    assert loader.load_scenario("base_case").scenario_shocks == ()
    assert loader.load_scenario("liquidity_stress").scenario_shocks == ()


def test_payment_schedule_entries_are_typed_correctly(loader):
    snap = loader.load_scenario("base_case")
    directions = {entry.direction for entry in snap.payment_schedule}
    assert directions == {CashFlowDirection.INFLOW, CashFlowDirection.OUTFLOW}


def test_fx_positions_are_typed_correctly(loader):
    snap = loader.load_scenario("base_case")
    assert all(isinstance(p.direction, FXDirection) for p in snap.fx_positions)


def test_load_unknown_scenario_raises_with_available_list(loader):
    with pytest.raises(ScenarioNotFoundError) as exc_info:
        loader.load_scenario("does_not_exist")
    assert "base_case" in str(exc_info.value)


def test_snapshot_is_immutable(loader):
    snap = loader.load_scenario("base_case")
    with pytest.raises(AttributeError):
        snap.scenario_name = "mutated"


def test_missing_required_key_raises_synthetic_data_error(tmp_path):
    incomplete = {"scenario": "broken", "description": "missing everything else"}
    scenario_path = tmp_path / "broken.yaml"
    scenario_path.write_text(yaml.safe_dump(incomplete), encoding="utf-8")

    broken_loader = SyntheticDataLoader(scenarios_dir=tmp_path)
    with pytest.raises(SyntheticDataError, match="missing required keys"):
        broken_loader.load_scenario("broken")


def test_invalid_investment_position_raises_synthetic_data_error(loader, tmp_path):
    base = loader.load_scenario("base_case")
    raw = yaml.safe_load((loader.scenarios_dir / "base_case.yaml").read_text(encoding="utf-8"))
    raw["investment_positions"][0]["face_value"] = "-1"  # negative, violates ge=0
    scenario_path = tmp_path / "bad_investment.yaml"
    scenario_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    broken_loader = SyntheticDataLoader(scenarios_dir=tmp_path)
    with pytest.raises(SyntheticDataError, match="investment_positions"):
        broken_loader.load_scenario("bad_investment")


def test_invalid_cash_position_raises_synthetic_data_error(loader, tmp_path):
    raw = yaml.safe_load((loader.scenarios_dir / "base_case.yaml").read_text(encoding="utf-8"))
    raw["cash_positions"]["HoldCo"][0]["currency"] = "USDD"  # fails CurrencyCode pattern
    scenario_path = tmp_path / "bad_cash.yaml"
    scenario_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    broken_loader = SyntheticDataLoader(scenarios_dir=tmp_path)
    with pytest.raises(SyntheticDataError, match="cash_positions"):
        broken_loader.load_scenario("bad_cash")
