"""Cash flow forecasting, working capital, and pattern analysis tools.

Known simplification: this project's synthetic data has no FX spot-rate
table (only a yield curve), so functions here that must consolidate across
entities into a single figure (get_cash_flow_forecast,
calculate_net_cash_position) operate on the USD-denominated subset only.
Non-USD cash and payments are excluded rather than silently blended into a
meaningless total — the same reasoning as tools/liquidity.py's
get_investment_portfolio.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from decimal import Decimal

from core.tool_registry import ToolError, tool
from data.synthetic_loader import CashFlowDirection, PaymentScheduleEntry, TreasurySnapshot
from models.base import ExactDecimal, TreasuryBaseModel
from models.financial import CashAnomaly, CashFlowForecast, CashPosition, SweepOpportunity, WorkingCapitalMetrics

MIN_OPERATING_BUFFER = Decimal("500000")
REPORTING_CURRENCY = "USD"


class PaymentPatternAnalysis(TreasuryBaseModel):
    """Inflow/outflow timing and counterparty concentration for one currency."""

    currency: str
    total_inflows: ExactDecimal
    total_outflows: ExactDecimal
    net: ExactDecimal
    inflow_count: int
    outflow_count: int
    largest_outflow: ExactDecimal
    most_frequent_counterparty_id: str


class ForecastVariance(TreasuryBaseModel):
    """Actual vs. forecast error over a matched-length series of periods."""

    mean_absolute_error: ExactDecimal
    mean_percentage_error: ExactDecimal
    total_actual: ExactDecimal
    total_forecast: ExactDecimal


def _usd_positions(snapshot: TreasurySnapshot) -> list[CashPosition]:
    return [
        pos
        for positions in snapshot.cash_positions.values()
        for pos in positions
        if pos.currency == REPORTING_CURRENCY
    ]


def _usd_payments(snapshot: TreasurySnapshot) -> list[PaymentScheduleEntry]:
    return [entry for entry in snapshot.payment_schedule if entry.currency == REPORTING_CURRENCY]


@tool
def get_cash_flow_forecast(snapshot: TreasurySnapshot, horizon_days: int) -> CashFlowForecast:
    """USD-denominated rolling cash flow forecast over the next horizon_days.

    Non-USD payment schedule entries are excluded (see module docstring).
    """
    if horizon_days <= 0:
        raise ToolError("horizon_days must be positive")

    as_of = min((pos.as_of.date() for positions in snapshot.cash_positions.values() for pos in positions), default=date.today())
    horizon_end = as_of + timedelta(days=horizon_days)

    payments_in_window = [p for p in _usd_payments(snapshot) if as_of <= p.date <= horizon_end]
    periods = sorted({p.date for p in payments_in_window})

    inflows: list[Decimal] = []
    outflows: list[Decimal] = []
    net: list[Decimal] = []
    for period in periods:
        day_inflow = sum((p.amount for p in payments_in_window if p.date == period and p.direction == CashFlowDirection.INFLOW), Decimal("0"))
        day_outflow = sum((p.amount for p in payments_in_window if p.date == period and p.direction == CashFlowDirection.OUTFLOW), Decimal("0"))
        inflows.append(day_inflow)
        outflows.append(day_outflow)
        net.append(day_inflow - day_outflow)

    return CashFlowForecast(entity="Consolidated (USD)", periods=periods, inflows=inflows, outflows=outflows, net=net)


@tool
def calculate_net_cash_position(snapshot: TreasurySnapshot) -> CashPosition:
    """Consolidated USD cash position across all entities (see module docstring)."""
    positions = _usd_positions(snapshot)
    if not positions:
        raise ToolError("snapshot has no USD cash positions")

    total = sum((p.amount for p in positions), Decimal("0"))
    latest_as_of = max(p.as_of for p in positions)
    return CashPosition(currency=REPORTING_CURRENCY, amount=total, account_id="CONSOLIDATED-USD", as_of=latest_as_of)


@tool
def analyse_payment_patterns(snapshot: TreasurySnapshot, currency: str = REPORTING_CURRENCY) -> PaymentPatternAnalysis:
    """Inflow/outflow timing and concentration analysis for one currency's payment schedule."""
    entries = [p for p in snapshot.payment_schedule if p.currency == currency]
    if not entries:
        raise ToolError(f"snapshot has no payment schedule entries in {currency}")

    inflows = [p for p in entries if p.direction == CashFlowDirection.INFLOW]
    outflows = [p for p in entries if p.direction == CashFlowDirection.OUTFLOW]
    total_inflows = sum((p.amount for p in inflows), Decimal("0"))
    total_outflows = sum((p.amount for p in outflows), Decimal("0"))

    counterparty_counts: dict[str, int] = {}
    for p in entries:
        counterparty_counts[p.counterparty_id] = counterparty_counts.get(p.counterparty_id, 0) + 1
    most_frequent_counterparty_id = max(counterparty_counts.items(), key=lambda kv: kv[1])[0]

    largest_outflow = max((p.amount for p in outflows), default=Decimal("0"))

    return PaymentPatternAnalysis(
        currency=currency,
        total_inflows=total_inflows,
        total_outflows=total_outflows,
        net=total_inflows - total_outflows,
        inflow_count=len(inflows),
        outflow_count=len(outflows),
        largest_outflow=largest_outflow,
        most_frequent_counterparty_id=most_frequent_counterparty_id,
    )


@tool
def calculate_working_capital_metrics(snapshot: TreasurySnapshot) -> WorkingCapitalMetrics:
    """DSO, DPO, CCC (= DSO - DPO, no inventory/DIO modelled), and days cash on hand."""
    if snapshot.annual_revenue <= 0:
        raise ToolError("annual_revenue must be positive")
    if snapshot.annual_cogs <= 0:
        raise ToolError("annual_cogs must be positive")

    dso = (snapshot.accounts_receivable / snapshot.annual_revenue) * Decimal("365")
    dpo = (snapshot.accounts_payable / snapshot.annual_cogs) * Decimal("365")
    ccc = dso - dpo
    days_cash_on_hand = snapshot.hqla / (snapshot.annual_cogs / Decimal("365"))

    return WorkingCapitalMetrics(dso=dso, dpo=dpo, ccc=ccc, days_cash_on_hand=days_cash_on_hand)


@tool
def detect_anomalies(entity: str, time_series: list[tuple[date, Decimal]], z_threshold: Decimal) -> list[CashAnomaly]:
    """Flag points in a (date, amount) time series more than z_threshold standard
    deviations from the series mean.
    """
    if len(time_series) < 2:
        raise ToolError("time_series must have at least 2 points to compute a standard deviation")
    if z_threshold <= 0:
        raise ToolError("z_threshold must be positive")

    values = [float(amount) for _, amount in time_series]
    mean = statistics.fmean(values)
    stdev = statistics.stdev(values)
    if stdev == 0:
        return []

    anomalies: list[CashAnomaly] = []
    for as_of, amount in time_series:
        z_score = (float(amount) - mean) / stdev
        if abs(z_score) >= float(z_threshold):
            anomalies.append(
                CashAnomaly(
                    entity=entity,
                    as_of=as_of,
                    expected_amount=Decimal(str(mean)),
                    actual_amount=amount,
                    z_score=Decimal(str(z_score)),
                    description=f"{amount} deviates {z_score:.2f} standard deviations from the series mean of {mean:.2f}",
                )
            )
    return anomalies


@tool
def calculate_sweep_opportunity(positions: list[CashPosition]) -> list[SweepOpportunity]:
    """Identify idle same-currency balances above the operating buffer that
    could be swept to that currency's largest-balance account.
    """
    if not positions:
        raise ToolError("positions must not be empty")

    opportunities: list[SweepOpportunity] = []
    for currency in sorted({p.currency for p in positions}):
        currency_positions = [p for p in positions if p.currency == currency]
        if len(currency_positions) < 2:
            continue
        target = max(currency_positions, key=lambda p: p.amount)
        for p in currency_positions:
            if p.account_id == target.account_id:
                continue
            excess = p.amount - MIN_OPERATING_BUFFER
            if excess > 0:
                opportunities.append(
                    SweepOpportunity(
                        from_account_id=p.account_id,
                        to_account_id=target.account_id,
                        currency=currency,
                        amount=excess,
                        rationale=f"Balance exceeds the {MIN_OPERATING_BUFFER} operating buffer for {currency}",
                    )
                )
    return opportunities


@tool
def calculate_forecast_variance(actual: list[Decimal], forecast: list[Decimal]) -> ForecastVariance:
    """Actual vs. forecast variance over a matched-length series of periods."""
    if not actual or not forecast:
        raise ToolError("actual and forecast must not be empty")
    if len(actual) != len(forecast):
        raise ToolError("actual and forecast must be the same length")

    total_actual = sum(actual, Decimal("0"))
    total_forecast = sum(forecast, Decimal("0"))

    absolute_errors = [abs(a - f) for a, f in zip(actual, forecast)]
    mean_absolute_error = sum(absolute_errors, Decimal("0")) / len(absolute_errors)

    percentage_errors = [
        (a - f) / a for a, f in zip(actual, forecast) if a != 0
    ]
    mean_percentage_error = (
        sum(percentage_errors, Decimal("0")) / len(percentage_errors) if percentage_errors else Decimal("0")
    )

    return ForecastVariance(
        mean_absolute_error=mean_absolute_error,
        mean_percentage_error=mean_percentage_error,
        total_actual=total_actual,
        total_forecast=total_forecast,
    )
