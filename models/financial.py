"""Core financial and treasury domain models.

Ratios (lcr, nsfr, hedge_ratio, confidence, ...) are represented as fractions,
not percentages — 1.42 means 142%. All monetary and ratio fields use
ExactDecimal (see models/base.py) per ADR-003.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import Field, model_validator

from models.base import ExactDecimal, TreasuryBaseModel

CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
CurrencyPair = Annotated[str, Field(pattern=r"^[A-Z]{3}/[A-Z]{3}$")]
# S&P/Fitch-style long-term rating scale, plus NR (not rated).
CreditRating = Annotated[str, Field(pattern=r"^(AAA|AA|A|BBB|BB|B|CCC|CC|C|D)[+-]?$|^NR$")]


class StressSeverity(str, Enum):
    """How badly a stress-test outcome breaches its liquidity target."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TrendDirection(str, Enum):
    """Slope sign of a fitted trend line."""

    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class AlertSeverity(str, Enum):
    """Priority of an alert-rule breach, from the rule catalogue in agent-specifications.md."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class CashPosition(TreasuryBaseModel):
    """A single account's cash balance in one currency, as of a point in time."""

    currency: CurrencyCode
    amount: ExactDecimal
    account_id: str
    as_of: datetime


class CashFlowForecast(TreasuryBaseModel):
    """A rolling cash flow forecast: parallel per-period inflow/outflow/net series."""

    entity: str
    periods: list[date]
    inflows: list[ExactDecimal]
    outflows: list[ExactDecimal]
    net: list[ExactDecimal]

    @model_validator(mode="after")
    def check_equal_lengths(self) -> "CashFlowForecast":
        lengths = {len(self.periods), len(self.inflows), len(self.outflows), len(self.net)}
        if len(lengths) > 1:
            raise ValueError("periods, inflows, outflows, and net must all be the same length")
        return self


class LiquidityMetrics(TreasuryBaseModel):
    """LCR/NSFR ratios alongside the HQLA and outflow figures behind them."""

    lcr: ExactDecimal = Field(ge=0)
    nsfr: ExactDecimal = Field(ge=0)
    hqla: ExactDecimal = Field(ge=0)
    net_outflows_30d: ExactDecimal


class CoverageRatios(TreasuryBaseModel):
    """LCR/NSFR ratios plus whether each meets the Basel III 100% minimum."""

    lcr_ratio: ExactDecimal = Field(ge=0)
    nsfr_ratio: ExactDecimal = Field(ge=0)
    lcr_compliant: bool
    nsfr_compliant: bool


class LiquidityGap(TreasuryBaseModel):
    """Net cash flow gap for one tenor bucket, plus the running cumulative gap."""

    tenor_bucket: str
    gap_amount: ExactDecimal
    cumulative_gap: ExactDecimal


class FXExposure(TreasuryBaseModel):
    """Gross long/short and net exposure for one currency pair, plus its hedge ratio."""

    currency_pair: CurrencyPair
    gross_long: ExactDecimal = Field(ge=0)
    gross_short: ExactDecimal = Field(ge=0)
    net: ExactDecimal
    hedge_ratio: ExactDecimal = Field(ge=0, le=1)


class VaRMetrics(TreasuryBaseModel):
    """Historical-simulation Value-at-Risk at 1-day and 10-day horizons."""

    confidence: ExactDecimal = Field(gt=0, lt=1)
    horizon_days: int = Field(gt=0)
    var_1d: ExactDecimal = Field(ge=0)
    var_10d: ExactDecimal = Field(ge=0)
    expected_shortfall: ExactDecimal = Field(ge=0)


class RateSensitivity(TreasuryBaseModel):
    """Portfolio interest-rate sensitivity: DV01, duration, and a parallel-shift P&L impact."""

    dv01: ExactDecimal
    modified_duration: ExactDecimal
    parallel_shift_impact: ExactDecimal


class CounterpartyRisk(TreasuryBaseModel):
    """Exposure to one counterparty, optionally broken out by currency."""

    counterparty_id: str
    gross_exposure: ExactDecimal = Field(ge=0)
    net_exposure: ExactDecimal
    credit_rating: CreditRating
    # Optional: exposure is often reported per-currency rather than blended
    # (no FX spot-rate table backs this project — see tools/risk.py). None
    # for a single-currency or already-converted figure.
    currency: CurrencyCode | None = None


class RiskSummary(TreasuryBaseModel):
    """TARA's top-level risk snapshot: total FX exposure, 1-day VaR, and the biggest named risks."""

    total_fx_exposure: ExactDecimal = Field(ge=0)
    var_1d: ExactDecimal = Field(ge=0)
    top_risks: list[str]


class WorkingCapitalMetrics(TreasuryBaseModel):
    """DSO, DPO, cash conversion cycle, and days cash on hand."""

    dso: ExactDecimal = Field(ge=0)
    dpo: ExactDecimal = Field(ge=0)
    ccc: ExactDecimal
    days_cash_on_hand: ExactDecimal = Field(ge=0)


class KPIScore(TreasuryBaseModel):
    """One metric's value against its target, with the resulting variance."""

    value: ExactDecimal
    target: ExactDecimal
    variance_pct: ExactDecimal
    on_target: bool


class KPIScorecard(TreasuryBaseModel):
    """A named set of KPIScores, keyed by metric name."""

    metrics: dict[str, KPIScore]


class StressTestResult(TreasuryBaseModel):
    """Post-stress LCR, any HQLA shortfall, and the resulting severity."""

    scenario_name: str
    lcr_post_stress: ExactDecimal = Field(ge=0)
    shortfall: ExactDecimal = Field(ge=0)
    severity: StressSeverity


class CashAnomaly(TreasuryBaseModel):
    """One flagged statistical outlier in a cash flow time series."""

    entity: str
    as_of: date
    expected_amount: ExactDecimal
    actual_amount: ExactDecimal
    z_score: ExactDecimal
    description: str


class SweepOpportunity(TreasuryBaseModel):
    """A suggested transfer of idle balance from one account to another."""

    from_account_id: str
    to_account_id: str
    currency: CurrencyCode
    amount: ExactDecimal = Field(ge=0)
    rationale: str


class ScenarioResult(TreasuryBaseModel):
    """P&L impact of applying one named shock scenario."""

    scenario_name: str
    pnl_impact: ExactDecimal
    description: str


class TrendInsight(TreasuryBaseModel):
    """Fitted direction and magnitude of a metric's trend over time."""

    metric_name: str
    direction: TrendDirection
    magnitude: ExactDecimal
    commentary: str


class BenchmarkResult(TreasuryBaseModel):
    """One metric compared against a synthetic peer set: median and percentile rank."""

    metric_name: str
    entity_value: ExactDecimal
    peer_median: ExactDecimal
    percentile_rank: ExactDecimal = Field(ge=0, le=100)
    commentary: str


class PriorityIssue(TreasuryBaseModel):
    """One open issue, weighted and ranked by severity, with a recommended owner."""

    issue: str
    category: str
    severity_score: ExactDecimal = Field(ge=0, le=100)
    recommended_owner: str


class AlertEvent(TreasuryBaseModel):
    """One alert-rule breach: the rule, the metric, and how far past threshold it is."""

    rule_id: str
    metric: str
    threshold: ExactDecimal
    actual_value: ExactDecimal
    severity: AlertSeverity
    message: str
    timestamp: datetime
    acknowledged: bool = False


class TriageRequest(TreasuryBaseModel):
    """ARIA's referral of one alert to the specialist best placed to handle it."""

    alert: AlertEvent
    recommended_agent: str
    note: str
