# TreasuryAI — Agent Specifications

## Shared Agent Contract

Every agent must conform to the following interface:

```python
class BaseAgent(ABC):
    agent_id: str                    # e.g. "ATLAS"
    display_name: str                # e.g. "Atlas — Treasury & Liquidity"
    system_prompt: str               # Fixed; defined in agent module
    tools: list[ToolDefinition]      # Subset of registered tools
    max_tokens: int                  # Per-call LLM cap

    @abstractmethod
    def run(self, request: AgentRequest) -> AgentResponse:
        ...
```

**Rules all agents must follow:**
1. Never perform arithmetic in the system prompt or in Python agent code — always call a tool.
2. Always populate `AgentResponse.reasoning` with a plain-English explanation of tool choices.
3. Always set `AgentResponse.status` to `PENDING_APPROVAL` when the output implies a consequential action.
4. Always log every tool call and response via `AuditLogger` before returning.

---

## ORION — Orchestrator Agent

### Role
ORION is the sole entry point for external requests. It parses user intent, decides which specialist agents to invoke (sequentially or in parallel where safe), aggregates their responses, and produces a unified final output.

### Responsibilities
- Intent classification: map user request to one or more workflows.
- Agent routing: invoke ATLAS, CORA, TARA, FIRA as needed.
- Response synthesis: merge specialist outputs into a coherent answer.
- Approval gate enforcement: any `PENDING_APPROVAL` response from a specialist propagates to the final output.
- Session management: assign and track `session_id`; own the audit log lifecycle.

### Boundaries (what ORION must NOT do)
- Must not perform financial analysis directly — always delegates to specialists.
- Must not bypass approval gates.
- Must not invoke ARIA directly; ARIA runs as a background monitor.

### Tools available to ORION
| Tool | Purpose |
|------|---------|
| `route_to_agent(agent_id, request)` | Internal routing call (not an LLM tool; handled in code) |
| `summarise_responses(responses[])` | LLM tool that asks the model to synthesise specialist outputs |

### System Prompt (excerpt)
```
You are ORION, the orchestrator of the TreasuryAI platform.
Your job is to understand the operator's request, decide which
specialist agents are needed, and synthesise their findings into
a clear, actionable briefing.

You NEVER perform financial calculations yourself.
You ALWAYS route quantitative questions to the appropriate specialist.
When any specialist flags a recommendation as PENDING_APPROVAL,
you MUST surface that status in your final response.
```

### Key Workflows
1. **Daily Treasury Briefing** — ATLAS → CORA → FIRA → synthesise.
2. **Liquidity Stress Test** — ATLAS (with stress scenario) → TARA → synthesise.
3. **FX Risk Review** — TARA → FIRA → synthesise.
4. **Ad-hoc Query** — parse intent → route to single specialist → return.
5. **Alert Triage** — receive ARIA alert → route to relevant specialist → synthesise recommended action.

### Output Model
```python
class OrionResponse(AgentResponse):
    session_id: str
    agents_invoked: list[str]
    specialist_summaries: dict[str, str]   # agent_id → one-paragraph summary
    final_briefing: str
    recommendations: list[Recommendation]
    approval_required: bool
    status: ResponseStatus                  # COMPLETE | PENDING_APPROVAL | ERROR
```

### Max tokens: 2048

---

## ATLAS — Treasury & Liquidity Agent

### Role
ATLAS monitors and analyses the organisation's treasury position and liquidity health. It is the primary agent for balance sheet liquidity, funding, and investment portfolio analysis.

### Responsibilities
- Compute and interpret Liquidity Coverage Ratio (LCR) and Net Stable Funding Ratio (NSFR).
- Analyse cash and investment portfolio composition.
- Identify liquidity gaps and funding mismatches.
- Recommend rebalancing actions (flagged as `PENDING_APPROVAL`).
- Support stress testing of the liquidity position under defined scenarios.

### Boundaries
- Must not execute trades or transfers.
- Must not make FX hedging recommendations (TARA's domain).
- All ratio calculations delegated to `tools/liquidity.py`.

### Tools available to ATLAS
| Tool | Module | Description |
|------|--------|-------------|
| `get_cash_position` | `tools/liquidity.py` | Returns current cash by currency and account |
| `calculate_lcr` | `tools/liquidity.py` | Basel III Liquidity Coverage Ratio |
| `calculate_nsfr` | `tools/liquidity.py` | Net Stable Funding Ratio |
| `calculate_liquidity_gap` | `tools/liquidity.py` | Gap analysis across tenor buckets |
| `get_investment_portfolio` | `tools/liquidity.py` | Synthetic portfolio snapshot |
| `run_liquidity_stress` | `tools/liquidity.py` | Apply shock to liquidity position |
| `calculate_concentration_risk` | `tools/liquidity.py` | Counterparty/instrument concentration |

### System Prompt (excerpt)
```
You are ATLAS, the Treasury & Liquidity specialist of TreasuryAI.
You analyse balance sheet liquidity using the tools provided.
You interpret regulatory ratios (LCR ≥ 100%, NSFR ≥ 100%)
and flag breaches or near-breaches as HIGH priority.
You NEVER calculate ratios yourself — always call the appropriate tool.
Recommendations to move funds or adjust portfolio composition
must always be marked PENDING_APPROVAL.
```

### Output Model
```python
class AtlasResponse(AgentResponse):
    liquidity_metrics: LiquidityMetrics
    coverage_ratios: CoverageRatios
    gaps_identified: list[LiquidityGap]
    recommendations: list[Recommendation]
    stress_results: StressTestResult | None
    status: ResponseStatus
```

### Max tokens: 1024

---

## CORA — Cash Operations Agent

### Role
CORA manages operational cash flow intelligence. It focuses on near-term (0–30 day) cash forecasting, payment scheduling analysis, and working capital optimisation.

### Responsibilities
- Generate and explain short-term cash flow forecasts.
- Analyse inflow/outflow patterns and seasonal trends.
- Identify cash concentration opportunities.
- Flag unusual payment activity for review.
- Support sweep and pooling analysis (recommendations only).

### Boundaries
- Must not initiate payments or transfers.
- Does not handle investment portfolio or regulatory liquidity ratios (ATLAS's domain).
- All forecast calculations delegated to `tools/cash_flow.py`.

### Tools available to CORA
| Tool | Module | Description |
|------|--------|-------------|
| `get_cash_flow_forecast` | `tools/cash_flow.py` | 30-day rolling forecast by entity |
| `calculate_net_cash_position` | `tools/cash_flow.py` | Consolidated net position |
| `analyse_payment_patterns` | `tools/cash_flow.py` | Inflow/outflow timing analysis |
| `calculate_working_capital_metrics` | `tools/cash_flow.py` | DPO, DSO, CCC |
| `detect_anomalies` | `tools/cash_flow.py` | Statistical outlier detection on cash flows |
| `calculate_sweep_opportunity` | `tools/cash_flow.py` | Inter-account optimisation analysis |
| `calculate_forecast_variance` | `tools/cash_flow.py` | Actual vs forecast variance |

### System Prompt (excerpt)
```
You are CORA, the Cash Operations specialist of TreasuryAI.
Your focus is the near-term (0–30 day) cash position, forecasting,
and working capital. Use the tools provided to analyse patterns
and flag anomalies. You do NOT manage the investment portfolio
or regulatory ratios — refer those questions to ATLAS.
Any recommendation to move, pool, or concentrate cash must
be marked PENDING_APPROVAL.
```

### Output Model
```python
class CoraResponse(AgentResponse):
    net_cash_position: CashPosition
    forecast_30d: CashFlowForecast
    working_capital: WorkingCapitalMetrics
    anomalies: list[CashAnomaly]
    sweep_opportunities: list[SweepOpportunity]
    recommendations: list[Recommendation]
    status: ResponseStatus
```

### Max tokens: 1024

---

## TARA — Treasury Risk Agent

### Role
TARA identifies, quantifies, and prioritises treasury-related financial risks including FX, interest rate, counterparty, and liquidity risk. It provides risk-adjusted analysis to support hedging and mitigation decisions.

### Responsibilities
- FX exposure calculation and hedging gap analysis.
- Interest rate sensitivity (duration, DV01).
- Value-at-Risk (VaR) estimation for the treasury portfolio.
- Counterparty credit risk assessment.
- Scenario and sensitivity analysis.

### Boundaries
- Must not recommend specific derivative instruments or counterparties by name.
- Does not generate market data — uses synthetic data from the data layer.
- All quantitative risk calculations delegated to `tools/risk.py`.

### Tools available to TARA
| Tool | Module | Description |
|------|--------|-------------|
| `calculate_fx_exposure` | `tools/risk.py` | Net FX exposure by currency pair |
| `calculate_var` | `tools/risk.py` | Historical simulation VaR (1-day, 10-day) |
| `calculate_duration` | `tools/risk.py` | Modified duration and DV01 |
| `calculate_hedge_effectiveness` | `tools/risk.py` | Hedge ratio and effectiveness score |
| `run_scenario_analysis` | `tools/risk.py` | P&L impact under named scenarios |
| `calculate_counterparty_exposure` | `tools/risk.py` | Gross/net exposure by counterparty |
| `calculate_interest_rate_sensitivity` | `tools/risk.py` | Rate shock impact on portfolio |

### System Prompt (excerpt)
```
You are TARA, the Treasury Risk specialist of TreasuryAI.
You identify and quantify financial risks in the treasury portfolio.
Use only the tools provided for all calculations.
Express risk in clear terms: exposure amounts, probability ranges,
and potential P&L impact. Always note confidence limitations
in model outputs. Hedging recommendations must be marked
PENDING_APPROVAL and framed as options, not directives.
```

### Output Model
```python
class TaraResponse(AgentResponse):
    risk_summary: RiskSummary
    fx_exposures: list[FXExposure]
    var_metrics: VaRMetrics
    rate_sensitivity: RateSensitivity
    counterparty_risks: list[CounterpartyRisk]
    scenario_results: list[ScenarioResult]
    recommendations: list[Recommendation]
    status: ResponseStatus
```

### Max tokens: 1024

---

## FIRA — Financial Intelligence Agent

### Role
FIRA provides analytical intelligence: benchmarking, trend analysis, KPI scoring, and narrative financial reporting. It contextualises the quantitative outputs of other agents within broader financial performance.

### Responsibilities
- KPI dashboarding and scoring against internal targets.
- Trend analysis across historical treasury data.
- Benchmarking against synthetic industry comparables.
- Generating plain-English financial narrative suitable for executive reporting.
- Answering ad-hoc analytical questions about treasury performance.

### Boundaries
- Does not perform risk or liquidity calculations — interprets outputs from ATLAS and TARA.
- Does not access live market data — uses synthetic benchmarks only.
- Narrative outputs are explanatory only; not a substitute for specialist agent outputs.

### Tools available to FIRA
| Tool | Module | Description |
|------|--------|-------------|
| `calculate_kpi_scores` | `tools/analytics.py` | Score treasury KPIs vs targets |
| `calculate_trend` | `tools/analytics.py` | Linear trend and momentum for a time series |
| `benchmark_metrics` | `tools/analytics.py` | Compare metrics to synthetic peer set |
| `calculate_variance_analysis` | `tools/analytics.py` | Budget vs actual variance |
| `generate_period_summary` | `tools/analytics.py` | Aggregate metrics over a date range |
| `rank_priorities` | `tools/analytics.py` | Sort issues by weighted severity score |

### System Prompt (excerpt)
```
You are FIRA, the Financial Intelligence specialist of TreasuryAI.
Your role is to provide analytical context and clear narrative
around treasury performance data. You interpret outputs from
other agents and from your own tools, producing clear summaries
for executive audiences. You do NOT perform risk or liquidity
calculations; refer those questions to TARA or ATLAS.
All outputs are informational — not recommendations requiring approval.
```

### Output Model
```python
class FiraResponse(AgentResponse):
    kpi_scorecard: KPIScorecard
    trend_insights: list[TrendInsight]
    benchmark_comparison: BenchmarkResult
    executive_narrative: str            # 2–4 paragraph plain-English summary
    priority_issues: list[PriorityIssue]
    status: ResponseStatus              # always COMPLETE (no approval gates)
```

### Max tokens: 1536

---

## ARIA — Monitoring & Alerts Agent

### Role
ARIA runs continuously (or on a scheduled basis) against live synthetic data streams, evaluating rules and thresholds. When conditions breach defined limits, ARIA emits structured `AlertEvent` objects and optionally triggers an ORION session for triage.

### Responsibilities
- Evaluate all configured alert rules against current data.
- Classify alerts by severity: `CRITICAL | HIGH | MEDIUM | LOW | INFO`.
- Emit structured `AlertEvent` objects to the alert log.
- Optionally invoke ORION with a triage request for `CRITICAL` and `HIGH` alerts.
- Track alert acknowledgement status.

### Boundaries
- ARIA does not perform deep analysis — it checks thresholds, not context.
- For any alert requiring interpretation, ARIA passes to ORION → specialist.
- ARIA does not trigger any consequential actions directly.

### Tools available to ARIA
| Tool | Module | Description |
|------|--------|-------------|
| `evaluate_alert_rules` | `tools/alerts.py` | Check all rules; return list of breaches |
| `classify_alert_severity` | `tools/alerts.py` | Assign severity level to a breach |
| `get_alert_history` | `tools/alerts.py` | Recent alerts for deduplication |
| `check_threshold` | `tools/alerts.py` | Single metric vs threshold check |
| `calculate_breach_magnitude` | `tools/alerts.py` | How far outside threshold (% or absolute) |

### Alert Rules (initial set)
| Rule ID | Metric | Threshold | Severity |
|---------|--------|-----------|----------|
| LIQ-001 | LCR | < 110% | CRITICAL |
| LIQ-002 | LCR | < 130% | HIGH |
| LIQ-003 | NSFR | < 105% | HIGH |
| CASH-001 | Net cash position | < 0 | CRITICAL |
| CASH-002 | Forecast deficit (7d) | > $5M | HIGH |
| FX-001 | Unhedged FX exposure | > $10M | HIGH |
| FX-002 | Unhedged FX exposure | > $20M | CRITICAL |
| IR-001 | DV01 | > $500k | HIGH |
| CP-001 | Counterparty concentration | > 25% | MEDIUM |

### System Prompt (excerpt)
```
You are ARIA, the Monitoring & Alerts agent of TreasuryAI.
Your job is to evaluate current financial metrics against
defined rules and emit clear, actionable alerts.
You do NOT perform root cause analysis — that is ORION's job.
For each breach, state: what metric breached, by how much,
and the recommended triage action (which specialist to consult).
```

### Output Model
```python
class AriaResponse(AgentResponse):
    alerts: list[AlertEvent]
    critical_count: int
    high_count: int
    triage_requests: list[TriageRequest]  # Sent to ORION for CRITICAL/HIGH
    status: ResponseStatus                # always COMPLETE
```

### Max tokens: 512 (alert evaluation is narrow and structured)

---

## Agent Interaction Matrix

| Caller → | ORION | ATLAS | CORA | TARA | FIRA | ARIA |
|----------|-------|-------|------|------|------|------|
| **User** | ✅ direct entry | ❌ | ❌ | ❌ | ❌ | ❌ |
| **ORION** | — | ✅ routes | ✅ routes | ✅ routes | ✅ routes | ❌ |
| **ARIA** | ✅ triage request | ❌ | ❌ | ❌ | ❌ | — |
| **ATLAS/CORA/TARA/FIRA** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

Specialist agents are isolated from each other. Cross-domain queries are always mediated by ORION.
