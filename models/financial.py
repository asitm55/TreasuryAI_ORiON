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
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TrendDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class AlertSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class CashPosition(TreasuryBaseModel):
    currency: CurrencyCode
    amount: ExactDecimal
    account_id: str
    as_of: datetime


class CashFlowForecast(TreasuryBaseModel):
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
    lcr: ExactDecimal = Field(ge=0)
    nsfr: ExactDecimal = Field(ge=0)
    hqla: ExactDecimal = Field(ge=0)
    net_outflows_30d: ExactDecimal


class CoverageRatios(TreasuryBaseModel):
    lcr_ratio: ExactDecimal = Field(ge=0)
    nsfr_ratio: ExactDecimal = Field(ge=0)
    lcr_compliant: bool
    nsfr_compliant: bool


class LiquidityGap(TreasuryBaseModel):
    tenor_bucket: str
    gap_amount: ExactDecimal
    cumulative_gap: ExactDecimal


class FXExposure(TreasuryBaseModel):
    currency_pair: CurrencyPair
    gross_long: ExactDecimal = Field(ge=0)
    gross_short: ExactDecimal = Field(ge=0)
    net: ExactDecimal
    hedge_ratio: ExactDecimal = Field(ge=0, le=1)


class VaRMetrics(TreasuryBaseModel):
    confidence: ExactDecimal = Field(gt=0, lt=1)
    horizon_days: int = Field(gt=0)
    var_1d: ExactDecimal = Field(ge=0)
    var_10d: ExactDecimal = Field(ge=0)
    expected_shortfall: ExactDecimal = Field(ge=0)


class RateSensitivity(TreasuryBaseModel):
    dv01: ExactDecimal
    modified_duration: ExactDecimal
    parallel_shift_impact: ExactDecimal


class CounterpartyRisk(TreasuryBaseModel):
    counterparty_id: str
    gross_exposure: ExactDecimal = Field(ge=0)
    net_exposure: ExactDecimal
    credit_rating: CreditRating
    # Optional: exposure is often reported per-currency rather than blended
    # (no FX spot-rate table backs this project — see tools/risk.py). None
    # for a single-currency or already-converted figure.
    currency: CurrencyCode | None = None


class RiskSummary(TreasuryBaseModel):
    total_fx_exposure: ExactDecimal = Field(ge=0)
    var_1d: ExactDecimal = Field(ge=0)
    top_risks: list[str]


class WorkingCapitalMetrics(TreasuryBaseModel):
    dso: ExactDecimal = Field(ge=0)
    dpo: ExactDecimal = Field(ge=0)
    ccc: ExactDecimal
    days_cash_on_hand: ExactDecimal = Field(ge=0)


class KPIScore(TreasuryBaseModel):
    value: ExactDecimal
    target: ExactDecimal
    variance_pct: ExactDecimal
    on_target: bool


class KPIScorecard(TreasuryBaseModel):
    metrics: dict[str, KPIScore]


class StressTestResult(TreasuryBaseModel):
    scenario_name: str
    lcr_post_stress: ExactDecimal = Field(ge=0)
    shortfall: ExactDecimal = Field(ge=0)
    severity: StressSeverity


class CashAnomaly(TreasuryBaseModel):
    entity: str
    as_of: date
    expected_amount: ExactDecimal
    actual_amount: ExactDecimal
    z_score: ExactDecimal
    description: str


class SweepOpportunity(TreasuryBaseModel):
    from_account_id: str
    to_account_id: str
    currency: CurrencyCode
    amount: ExactDecimal = Field(ge=0)
    rationale: str


class ScenarioResult(TreasuryBaseModel):
    scenario_name: str
    pnl_impact: ExactDecimal
    description: str


class TrendInsight(TreasuryBaseModel):
    metric_name: str
    direction: TrendDirection
    magnitude: ExactDecimal
    commentary: str


class BenchmarkResult(TreasuryBaseModel):
    metric_name: str
    entity_value: ExactDecimal
    peer_median: ExactDecimal
    percentile_rank: ExactDecimal = Field(ge=0, le=100)
    commentary: str


class PriorityIssue(TreasuryBaseModel):
    issue: str
    category: str
    severity_score: ExactDecimal = Field(ge=0, le=100)
    recommended_owner: str


class AlertEvent(TreasuryBaseModel):
    rule_id: str
    metric: str
    threshold: ExactDecimal
    actual_value: ExactDecimal
    severity: AlertSeverity
    message: str
    timestamp: datetime
    acknowledged: bool = False


class TriageRequest(TreasuryBaseModel):
    alert: AlertEvent
    recommended_agent: str
    note: str
