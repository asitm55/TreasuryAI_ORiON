"""FX, VaR, duration, hedge, scenario, and counterparty risk tools.

Known simplifications (this is a portfolio/demo project, not a production
risk engine — see ADR-008's "simple over clever" and each function's
docstring for details):
  - calculate_var: historical simulation only, no parametric/Monte Carlo.
  - calculate_duration / calculate_interest_rate_sensitivity: approximate a
    bullet instrument's modified duration with its time to maturity, since
    the synthetic data models face value + coupon + maturity, not a full
    intermediate cash-flow schedule.
  - calculate_hedge_effectiveness: a simple notional-ratio proxy, not the
    dollar-offset regression method ASC 815/IFRS 9 actually require.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.tool_registry import ToolError, tool
from data.synthetic_loader import FXDirection, FXShockAssumption, InvestmentPosition, TreasurySnapshot
from models.base import ExactDecimal, TreasuryBaseModel
from models.financial import CounterpartyRisk, FXExposure, RateSensitivity, ScenarioResult, VaRMetrics


class DurationResult(TreasuryBaseModel):
    """Present value, Macaulay/modified duration, and DV01 for a set of cash flows."""

    present_value: ExactDecimal
    macaulay_duration: ExactDecimal
    modified_duration: ExactDecimal
    dv01: ExactDecimal


class HedgeEffectiveness(TreasuryBaseModel):
    """Notional-ratio hedge effectiveness proxy (see module docstring)."""

    hedge_ratio: ExactDecimal
    effectiveness_score: ExactDecimal
    classification: str


@tool
def calculate_fx_exposure(snapshot: TreasurySnapshot) -> list[FXExposure]:
    """Net FX exposure and hedge ratio per currency pair in the FX book."""
    if not snapshot.fx_positions:
        raise ToolError("snapshot has no FX positions")

    exposures: list[FXExposure] = []
    for pair in sorted({p.currency_pair for p in snapshot.fx_positions}):
        pair_positions = [p for p in snapshot.fx_positions if p.currency_pair == pair]
        gross_long = sum((p.notional for p in pair_positions if p.direction == FXDirection.LONG), Decimal("0"))
        gross_short = sum((p.notional for p in pair_positions if p.direction == FXDirection.SHORT), Decimal("0"))
        total_notional = sum((p.notional for p in pair_positions), Decimal("0"))
        hedged_notional = sum((p.notional for p in pair_positions if p.hedge_designated), Decimal("0"))
        hedge_ratio = hedged_notional / total_notional if total_notional > 0 else Decimal("0")

        exposures.append(
            FXExposure(
                currency_pair=pair,
                gross_long=gross_long,
                gross_short=gross_short,
                net=gross_long - gross_short,
                hedge_ratio=hedge_ratio,
            )
        )
    return exposures


@tool
def calculate_var(returns: list[Decimal], confidence: Decimal, horizon_days: int) -> VaRMetrics:
    """Historical-simulation VaR from a P&L series sampled at horizon_days.

    var_1d/var_10d are both derived from the same historical sample via
    square-root-of-time scaling: pass a series of horizon_days-period P&L
    observations and the function scales to the other Basel-standard
    horizon. expected_shortfall is the mean loss beyond the VaR threshold.
    """
    if len(returns) < 2:
        raise ToolError("returns must have at least 2 observations")
    if not (Decimal("0") < confidence < Decimal("1")):
        raise ToolError("confidence must be strictly between 0 and 1")
    if horizon_days <= 0:
        raise ToolError("horizon_days must be positive")

    sorted_returns = sorted(returns)
    tail_index = int((Decimal("1") - confidence) * len(sorted_returns))
    tail_index = min(max(tail_index, 0), len(sorted_returns) - 1)

    var_at_horizon = -sorted_returns[tail_index]
    tail_losses = sorted_returns[: tail_index + 1]
    expected_shortfall = -(sum(tail_losses, Decimal("0")) / len(tail_losses))

    scale = Decimal(horizon_days).sqrt()
    var_1day_equivalent = var_at_horizon / scale
    var_10day_equivalent = var_1day_equivalent * Decimal(10).sqrt()

    return VaRMetrics(
        confidence=confidence,
        horizon_days=horizon_days,
        var_1d=max(var_1day_equivalent, Decimal("0")),
        var_10d=max(var_10day_equivalent, Decimal("0")),
        expected_shortfall=max(expected_shortfall, Decimal("0")),
    )


@tool
def calculate_duration(cash_flows: list[tuple[Decimal, Decimal]], discount_rates: list[Decimal]) -> DurationResult:
    """Macaulay/modified duration and DV01 from (time_years, amount) cash flows
    and a parallel list of per-cash-flow discount rates.
    """
    if not cash_flows:
        raise ToolError("cash_flows must not be empty")
    if len(cash_flows) != len(discount_rates):
        raise ToolError("cash_flows and discount_rates must be the same length")

    present_values: list[Decimal] = []
    for (time_years, amount), rate in zip(cash_flows, discount_rates):
        if time_years < 0:
            raise ToolError("time_years must not be negative")
        pv = amount / (Decimal("1") + rate) ** time_years
        present_values.append(pv)

    total_pv = sum(present_values, Decimal("0"))
    if total_pv <= 0:
        raise ToolError("total present value must be positive")

    macaulay_duration = sum(
        (time_years * pv for (time_years, _), pv in zip(cash_flows, present_values)), Decimal("0")
    ) / total_pv

    weighted_rate = sum((rate * pv for rate, pv in zip(discount_rates, present_values)), Decimal("0")) / total_pv
    modified_duration = macaulay_duration / (Decimal("1") + weighted_rate)
    dv01 = modified_duration * total_pv * Decimal("0.0001")

    return DurationResult(
        present_value=total_pv,
        macaulay_duration=macaulay_duration,
        modified_duration=modified_duration,
        dv01=dv01,
    )


@tool
def calculate_hedge_effectiveness(hedged: Decimal, unhedged: Decimal) -> HedgeEffectiveness:
    """Notional-ratio hedge effectiveness proxy (see module docstring)."""
    if hedged < 0 or unhedged < 0:
        raise ToolError("hedged and unhedged must not be negative")
    total = hedged + unhedged
    if total <= 0:
        raise ToolError("hedged + unhedged must be positive")

    hedge_ratio = hedged / total
    effectiveness_score = hedge_ratio * Decimal("100")

    if hedge_ratio >= Decimal("0.8"):
        classification = "HIGHLY_EFFECTIVE"
    elif hedge_ratio >= Decimal("0.5"):
        classification = "PARTIALLY_EFFECTIVE"
    else:
        classification = "INEFFECTIVE"

    return HedgeEffectiveness(hedge_ratio=hedge_ratio, effectiveness_score=effectiveness_score, classification=classification)


@tool
def run_scenario_analysis(
    snapshot: TreasurySnapshot, scenario_params: list[FXShockAssumption] | None = None
) -> list[ScenarioResult]:
    """P&L impact of applying each FX shock assumption to the current FX book.

    Defaults to snapshot.scenario_shocks when scenario_params is omitted.
    """
    shocks = scenario_params if scenario_params is not None else list(snapshot.scenario_shocks)
    if not shocks:
        raise ToolError("no scenario_shocks to analyse")

    exposures = {e.currency_pair: e for e in calculate_fx_exposure(snapshot)}

    results: list[ScenarioResult] = []
    for shock in shocks:
        exposure = exposures.get(shock.currency_pair)
        net_exposure = exposure.net if exposure else Decimal("0")
        pnl_impact = net_exposure * shock.shock_pct
        results.append(
            ScenarioResult(
                scenario_name=f"{shock.currency_pair} {shock.shock_pct:+.2%} shock",
                pnl_impact=pnl_impact,
                description=(
                    f"Net {shock.currency_pair} exposure of {net_exposure} moved by "
                    f"{shock.shock_pct:+.2%}, producing a P&L impact of {pnl_impact}."
                ),
            )
        )
    return results


@tool
def calculate_counterparty_exposure(snapshot: TreasurySnapshot) -> list[CounterpartyRisk]:
    """Gross investment exposure per counterparty, broken out by currency (no
    FX conversion is performed — see module docstring). No netting
    agreements are modelled, so net_exposure equals gross_exposure. A
    counterparty with no investment positions is omitted.
    """
    if not snapshot.counterparties:
        raise ToolError("snapshot has no counterparties")

    exposures: list[CounterpartyRisk] = []
    for cp in snapshot.counterparties:
        cp_positions = [p for p in snapshot.investment_positions if p.counterparty_id == cp.counterparty_id]
        for currency in sorted({p.currency for p in cp_positions}):
            gross = sum((p.market_value for p in cp_positions if p.currency == currency), Decimal("0"))
            exposures.append(
                CounterpartyRisk(
                    counterparty_id=cp.counterparty_id,
                    gross_exposure=gross,
                    net_exposure=gross,
                    credit_rating=cp.credit_rating,
                    currency=currency,
                )
            )
    return exposures


@tool
def calculate_interest_rate_sensitivity(
    portfolio: list[InvestmentPosition], rate_shock_bps: int, as_of: date | None = None
) -> RateSensitivity:
    """Portfolio DV01 and duration, approximating each bullet instrument's
    modified duration with its time to maturity (see module docstring).
    """
    if not portfolio:
        raise ToolError("portfolio must not be empty")

    valuation_date = as_of or date.today()

    total_dv01 = Decimal("0")
    weighted_duration_numerator = Decimal("0")
    total_market_value = Decimal("0")

    for position in portfolio:
        years_to_maturity = Decimal((position.maturity_date - valuation_date).days) / Decimal("365")
        if years_to_maturity <= 0:
            continue
        position_dv01 = position.market_value * years_to_maturity * Decimal("0.0001")
        total_dv01 += position_dv01
        weighted_duration_numerator += years_to_maturity * position.market_value
        total_market_value += position.market_value

    if total_market_value <= 0:
        raise ToolError("portfolio has no positions with positive remaining maturity")

    modified_duration = weighted_duration_numerator / total_market_value
    parallel_shift_impact = -total_dv01 * Decimal(rate_shock_bps)

    return RateSensitivity(dv01=total_dv01, modified_duration=modified_duration, parallel_shift_impact=parallel_shift_impact)
