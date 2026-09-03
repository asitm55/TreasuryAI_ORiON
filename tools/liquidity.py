"""Liquidity ratios, coverage, and portfolio tools. See ADR-001: LLMs never
calculate — every number an agent reports must trace back to a call here.
"""

from __future__ import annotations

from decimal import Decimal

from core.tool_registry import ToolError, tool
from data.synthetic_loader import InvestmentPosition, TreasurySnapshot
from models.base import ExactDecimal, TreasuryBaseModel
from models.financial import CashPosition, CurrencyCode, LiquidityGap, StressSeverity, StressTestResult

CONCENTRATION_THRESHOLD = Decimal("0.25")  # matches alert rule CP-001


class LCRResult(TreasuryBaseModel):
    """Basel III Liquidity Coverage Ratio and whether it meets the 100% minimum."""

    ratio: ExactDecimal
    compliant: bool


class NSFRResult(TreasuryBaseModel):
    """Net Stable Funding Ratio and whether it meets the 100% minimum."""

    ratio: ExactDecimal
    compliant: bool


class InvestmentPortfolio(TreasuryBaseModel):
    """The investment book plus per-currency totals (never blended - see below)."""

    positions: tuple[InvestmentPosition, ...]
    # Totals are broken out per currency, never blended: this project has no
    # FX spot-rate table, so summing e.g. USD and JPY face values into one
    # number would silently produce a meaningless figure.
    total_face_value_by_currency: dict[str, ExactDecimal]
    total_market_value_by_currency: dict[str, ExactDecimal]
    hqla_eligible_value_by_currency: dict[str, ExactDecimal]


class CurrencyConcentration(TreasuryBaseModel):
    """Counterparty concentration within one currency's investment positions."""

    currency: CurrencyCode
    total_market_value: ExactDecimal
    by_counterparty_pct: dict[str, ExactDecimal]
    largest_counterparty_id: str
    largest_concentration_pct: ExactDecimal
    exceeds_threshold: bool


class ConcentrationRisk(TreasuryBaseModel):
    """Counterparty concentration across the investment book, broken out per currency.

    Concentration is computed within each currency, not blended across
    them, for the same reason as InvestmentPortfolio above.
    """

    by_currency: tuple[CurrencyConcentration, ...]
    exceeds_threshold: bool


@tool
def get_cash_position(snapshot: TreasurySnapshot) -> list[CashPosition]:
    """Return every cash position across all entities in the snapshot."""
    return [pos for positions in snapshot.cash_positions.values() for pos in positions]


@tool
def calculate_lcr(hqla: Decimal, net_cash_outflows_30d: Decimal) -> LCRResult:
    """Basel III Liquidity Coverage Ratio: HQLA / net 30-day cash outflows."""
    if hqla < 0:
        raise ToolError("hqla must not be negative")
    if net_cash_outflows_30d <= 0:
        raise ToolError("net_cash_outflows_30d must be positive")
    ratio = hqla / net_cash_outflows_30d
    return LCRResult(ratio=ratio, compliant=ratio >= Decimal("1.0"))


@tool
def calculate_nsfr(available_stable_funding: Decimal, required_stable_funding: Decimal) -> NSFRResult:
    """Net Stable Funding Ratio: available / required stable funding."""
    if available_stable_funding < 0:
        raise ToolError("available_stable_funding must not be negative")
    if required_stable_funding <= 0:
        raise ToolError("required_stable_funding must be positive")
    ratio = available_stable_funding / required_stable_funding
    return NSFRResult(ratio=ratio, compliant=ratio >= Decimal("1.0"))


@tool
def calculate_liquidity_gap(cash_flows_by_tenor: dict[str, Decimal]) -> list[LiquidityGap]:
    """Gap analysis across tenor buckets, in the order the mapping is given.

    cumulative_gap is a running total across buckets in insertion order, so
    callers must pass buckets ordered from nearest to furthest tenor.
    """
    if not cash_flows_by_tenor:
        raise ToolError("cash_flows_by_tenor must not be empty")

    gaps: list[LiquidityGap] = []
    running_total = Decimal("0")
    for bucket, amount in cash_flows_by_tenor.items():
        running_total += amount
        gaps.append(LiquidityGap(tenor_bucket=bucket, gap_amount=amount, cumulative_gap=running_total))
    return gaps


@tool
def get_investment_portfolio(snapshot: TreasurySnapshot) -> InvestmentPortfolio:
    """Aggregate the snapshot's investment book into a portfolio summary."""
    positions = snapshot.investment_positions
    if not positions:
        raise ToolError("snapshot has no investment positions")

    currencies = {p.currency for p in positions}
    total_face_value_by_currency = {
        ccy: sum((p.face_value for p in positions if p.currency == ccy), Decimal("0")) for ccy in currencies
    }
    total_market_value_by_currency = {
        ccy: sum((p.market_value for p in positions if p.currency == ccy), Decimal("0")) for ccy in currencies
    }
    hqla_eligible_value_by_currency = {
        ccy: sum((p.market_value for p in positions if p.currency == ccy and p.hqla_eligible), Decimal("0"))
        for ccy in currencies
    }

    return InvestmentPortfolio(
        positions=positions,
        total_face_value_by_currency=total_face_value_by_currency,
        total_market_value_by_currency=total_market_value_by_currency,
        hqla_eligible_value_by_currency=hqla_eligible_value_by_currency,
    )


@tool
def run_liquidity_stress(snapshot: TreasurySnapshot, outflow_shock_pct: Decimal) -> StressTestResult:
    """Apply a proportional shock to net 30-day outflows and re-run LCR.

    outflow_shock_pct=0.30 means "outflows increase by 30%".
    """
    if outflow_shock_pct <= Decimal("-1"):
        raise ToolError("outflow_shock_pct must be greater than -1 (outflows cannot go negative)")

    shocked_outflows = snapshot.net_cash_outflows_30d * (Decimal("1") + outflow_shock_pct)
    if shocked_outflows <= 0:
        raise ToolError("shocked net_cash_outflows_30d must be positive")

    lcr_post_stress = snapshot.hqla / shocked_outflows
    shortfall = max(Decimal("0"), shocked_outflows - snapshot.hqla)

    if lcr_post_stress >= Decimal("1.20"):
        severity = StressSeverity.LOW
    elif lcr_post_stress >= Decimal("1.10"):
        severity = StressSeverity.MEDIUM
    elif lcr_post_stress >= Decimal("1.00"):
        severity = StressSeverity.HIGH
    else:
        severity = StressSeverity.CRITICAL

    return StressTestResult(
        scenario_name=snapshot.scenario_name,
        lcr_post_stress=lcr_post_stress,
        shortfall=shortfall,
        severity=severity,
    )


@tool
def calculate_concentration_risk(positions: list[InvestmentPosition]) -> ConcentrationRisk:
    """Counterparty concentration as a % of investment portfolio market value,
    computed separately within each currency (no FX conversion is performed
    — see ConcentrationRisk).
    """
    if not positions:
        raise ToolError("positions must not be empty")

    by_currency: list[CurrencyConcentration] = []
    for currency in sorted({p.currency for p in positions}):
        currency_positions = [p for p in positions if p.currency == currency]
        total_market_value = sum((p.market_value for p in currency_positions), Decimal("0"))
        if total_market_value <= 0:
            raise ToolError(f"total market value for {currency} must be positive")

        by_counterparty: dict[str, Decimal] = {}
        for p in currency_positions:
            by_counterparty[p.counterparty_id] = by_counterparty.get(p.counterparty_id, Decimal("0")) + p.market_value

        by_counterparty_pct = {cp: value / total_market_value for cp, value in by_counterparty.items()}
        largest_counterparty_id, largest_pct = max(by_counterparty_pct.items(), key=lambda kv: kv[1])

        by_currency.append(
            CurrencyConcentration(
                currency=currency,
                total_market_value=total_market_value,
                by_counterparty_pct=by_counterparty_pct,
                largest_counterparty_id=largest_counterparty_id,
                largest_concentration_pct=largest_pct,
                exceeds_threshold=largest_pct > CONCENTRATION_THRESHOLD,
            )
        )

    return ConcentrationRisk(
        by_currency=tuple(by_currency),
        exceeds_threshold=any(c.exceeds_threshold for c in by_currency),
    )
