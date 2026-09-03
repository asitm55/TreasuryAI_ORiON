"""Synthetic treasury data layer. See ADR-007: synthetic data only.

Scenario YAML files under data/scenarios/ are hand-curated, deterministic
snapshots of a fictional treasury (HoldCo + two OpCos). load_scenario()
validates each section against a typed Pydantic model and assembles an
immutable TreasurySnapshot.

Note on hqla / net_cash_outflows_30d / available_stable_funding /
required_stable_funding: these four scalars are the direct inputs to
tools/liquidity.py's calculate_lcr(hqla, net_cash_outflows_30d) and
calculate_nsfr(available_stable_funding, required_stable_funding), per the
signatures in architecture.md and implementation-plan.md. Basel LCR/NSFR
run-off rates and haircuts are themselves calibration parameters, not
something this project derives bottom-up from position-level data — so the
scenario file states them directly, decoupled from the granular cash /
investment / payment data that feeds the other tools (cash flow, FX, risk).

annual_revenue / annual_cogs / accounts_receivable / accounts_payable were
added in Phase 3 for the same reason: tools/cash_flow.py's
calculate_working_capital_metrics needs DSO/DPO/CCC inputs that no amount of
position-level data derives (this synthetic treasury has no AR/AP ledger or
income statement), so they're stated directly as scenario-level scalars too.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, ValidationError

from models.base import ExactDecimal, TreasuryBaseModel
from models.financial import CreditRating, CurrencyCode, CurrencyPair
from models.financial import CashPosition

DEFAULT_SCENARIOS_DIR = Path(__file__).parent / "scenarios"


class ScenarioNotFoundError(FileNotFoundError):
    def __init__(self, name: str, scenarios_dir: Path):
        available = sorted(p.stem for p in scenarios_dir.glob("*.yaml"))
        super().__init__(
            f"Scenario '{name}' not found in {scenarios_dir}. Available: {available}"
        )


class SyntheticDataError(ValueError):
    """Raised when a scenario YAML fails schema validation."""


class FXDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class CashFlowDirection(str, Enum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"


class InvestmentPosition(TreasuryBaseModel):
    instrument_id: str
    entity: str
    instrument_type: str
    currency: CurrencyCode
    face_value: ExactDecimal = Field(ge=0)
    market_value: ExactDecimal = Field(ge=0)
    maturity_date: date
    coupon_rate: ExactDecimal = Field(ge=0)
    counterparty_id: str
    hqla_eligible: bool = False


class FXBookEntry(TreasuryBaseModel):
    position_id: str
    entity: str
    currency_pair: CurrencyPair
    notional: ExactDecimal = Field(ge=0)
    direction: FXDirection
    trade_date: date
    maturity_date: date
    hedge_designated: bool = False


class PaymentScheduleEntry(TreasuryBaseModel):
    entity: str
    date: date
    currency: CurrencyCode
    amount: ExactDecimal = Field(ge=0)
    direction: CashFlowDirection
    counterparty_id: str
    description: str


class CounterpartyProfile(TreasuryBaseModel):
    counterparty_id: str
    name: str
    credit_rating: CreditRating
    sector: str
    exposure_limit: ExactDecimal = Field(ge=0)


class RateCurvePoint(TreasuryBaseModel):
    currency: CurrencyCode
    tenor: str
    rate: ExactDecimal


class FXShockAssumption(TreasuryBaseModel):
    currency_pair: CurrencyPair
    shock_pct: ExactDecimal


@dataclass(frozen=True)
class TreasurySnapshot:
    scenario_name: str
    description: str
    entities: tuple[str, ...]
    currencies: tuple[str, ...]

    hqla: Decimal
    net_cash_outflows_30d: Decimal
    available_stable_funding: Decimal
    required_stable_funding: Decimal
    annual_revenue: Decimal
    annual_cogs: Decimal
    accounts_receivable: Decimal
    accounts_payable: Decimal

    cash_positions: dict[str, tuple[CashPosition, ...]]
    investment_positions: tuple[InvestmentPosition, ...]
    fx_positions: tuple[FXBookEntry, ...]
    payment_schedule: tuple[PaymentScheduleEntry, ...]
    counterparties: tuple[CounterpartyProfile, ...]
    rate_curve: tuple[RateCurvePoint, ...]
    scenario_shocks: tuple[FXShockAssumption, ...] = ()


def _build_model_list(raw_items: list[dict[str, Any]], model: type[TreasuryBaseModel], section: str, scenario_name: str) -> tuple:
    try:
        return tuple(model(**item) for item in raw_items)
    except ValidationError as exc:
        raise SyntheticDataError(
            f"Scenario '{scenario_name}': invalid '{section}' entry.\n{exc}"
        ) from exc


class SyntheticDataLoader:
    def __init__(self, scenarios_dir: str | os.PathLike | None = None):
        self.scenarios_dir = Path(scenarios_dir) if scenarios_dir else DEFAULT_SCENARIOS_DIR

    def list_scenarios(self) -> list[str]:
        return sorted(p.stem for p in self.scenarios_dir.glob("*.yaml"))

    def load_scenario(self, name: str) -> TreasurySnapshot:
        path = self.scenarios_dir / f"{name}.yaml"
        if not path.exists():
            raise ScenarioNotFoundError(name, self.scenarios_dir)

        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        required_keys = {
            "scenario", "description", "entities", "currencies",
            "hqla", "net_cash_outflows_30d", "available_stable_funding",
            "required_stable_funding", "annual_revenue", "annual_cogs",
            "accounts_receivable", "accounts_payable",
            "cash_positions", "investment_positions",
            "fx_positions", "payment_schedule", "counterparties", "rate_curve",
        }
        missing = required_keys - raw.keys()
        if missing:
            raise SyntheticDataError(f"Scenario '{name}' is missing required keys: {sorted(missing)}")

        try:
            cash_positions = {
                entity: tuple(CashPosition(**pos) for pos in positions)
                for entity, positions in raw["cash_positions"].items()
            }
        except ValidationError as exc:
            raise SyntheticDataError(f"Scenario '{name}': invalid 'cash_positions' entry.\n{exc}") from exc

        return TreasurySnapshot(
            scenario_name=raw["scenario"],
            description=raw["description"],
            entities=tuple(raw["entities"]),
            currencies=tuple(raw["currencies"]),
            hqla=Decimal(str(raw["hqla"])),
            net_cash_outflows_30d=Decimal(str(raw["net_cash_outflows_30d"])),
            available_stable_funding=Decimal(str(raw["available_stable_funding"])),
            required_stable_funding=Decimal(str(raw["required_stable_funding"])),
            annual_revenue=Decimal(str(raw["annual_revenue"])),
            annual_cogs=Decimal(str(raw["annual_cogs"])),
            accounts_receivable=Decimal(str(raw["accounts_receivable"])),
            accounts_payable=Decimal(str(raw["accounts_payable"])),
            cash_positions=cash_positions,
            investment_positions=_build_model_list(raw["investment_positions"], InvestmentPosition, "investment_positions", name),
            fx_positions=_build_model_list(raw["fx_positions"], FXBookEntry, "fx_positions", name),
            payment_schedule=_build_model_list(raw["payment_schedule"], PaymentScheduleEntry, "payment_schedule", name),
            counterparties=_build_model_list(raw["counterparties"], CounterpartyProfile, "counterparties", name),
            rate_curve=_build_model_list(raw["rate_curve"], RateCurvePoint, "rate_curve", name),
            scenario_shocks=_build_model_list(raw.get("scenario_shocks", []), FXShockAssumption, "scenario_shocks", name),
        )
