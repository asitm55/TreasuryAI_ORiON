"""Agent output models."""

from __future__ import annotations

from enum import Enum

from models.base import TreasuryBaseModel
from models.financial import (
    AlertEvent,
    BenchmarkResult,
    CashAnomaly,
    CashPosition,
    CashFlowForecast,
    CounterpartyRisk,
    CoverageRatios,
    FXExposure,
    KPIScorecard,
    LiquidityGap,
    LiquidityMetrics,
    PriorityIssue,
    RateSensitivity,
    RiskSummary,
    ScenarioResult,
    StressTestResult,
    SweepOpportunity,
    TrendInsight,
    TriageRequest,
    VaRMetrics,
    WorkingCapitalMetrics,
)


class ResponseStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ERROR = "ERROR"


class Recommendation(TreasuryBaseModel):
    action: str
    rationale: str
    estimated_impact: str
    requires_approval: bool


class AgentResponse(TreasuryBaseModel):
    agent_id: str
    request_id: str
    status: ResponseStatus
    reasoning: str
    raw_llm_output: str | None = None


class AtlasResponse(AgentResponse):
    liquidity_metrics: LiquidityMetrics
    coverage_ratios: CoverageRatios
    gaps_identified: list[LiquidityGap]
    recommendations: list[Recommendation]
    stress_results: StressTestResult | None = None


class CoraResponse(AgentResponse):
    net_cash_position: CashPosition
    forecast_30d: CashFlowForecast
    working_capital: WorkingCapitalMetrics
    anomalies: list[CashAnomaly]
    sweep_opportunities: list[SweepOpportunity]
    recommendations: list[Recommendation]


class TaraResponse(AgentResponse):
    risk_summary: RiskSummary
    fx_exposures: list[FXExposure]
    var_metrics: VaRMetrics
    rate_sensitivity: RateSensitivity
    counterparty_risks: list[CounterpartyRisk]
    scenario_results: list[ScenarioResult]
    recommendations: list[Recommendation]


class FiraResponse(AgentResponse):
    kpi_scorecard: KPIScorecard
    trend_insights: list[TrendInsight]
    benchmark_comparison: BenchmarkResult
    executive_narrative: str
    priority_issues: list[PriorityIssue]


class AriaResponse(AgentResponse):
    alerts: list[AlertEvent]
    critical_count: int
    high_count: int
    triage_requests: list[TriageRequest]


class OrionResponse(AgentResponse):
    session_id: str
    agents_invoked: list[str]
    specialist_summaries: dict[str, str]
    final_briefing: str
    recommendations: list[Recommendation]
    approval_required: bool
