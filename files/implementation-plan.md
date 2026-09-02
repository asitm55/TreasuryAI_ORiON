# TreasuryAI — Implementation Plan

## Guiding Principle

Build from the inside out: data models → tools → agents → orchestrator → UI. Each layer is testable before the next is built. At no point does the project require all layers to be complete to demonstrate value.

---

## Phase 0 — Project Scaffolding (½ day)

**Goal:** Empty but fully wired skeleton that runs without errors.

### Tasks
- [ ] Initialise `pyproject.toml` with dependencies (anthropic, pydantic, pyyaml, rich, pytest)
- [ ] Create `requirements.txt`
- [ ] Create all `__init__.py` files across `agents/`, `tools/`, `models/`, `core/`, `data/`
- [ ] Create `core/config.py` — reads env vars, provides `Settings` singleton
- [ ] Create stub `main.py` CLI entry point (no logic yet)
- [ ] Create `.env.example`
- [ ] Create `README.md` with install + run instructions
- [ ] Confirm `python main.py --help` runs without import errors

### Deliverable
```
$ python main.py --help
TreasuryAI v0.1.0 — Finance & Treasury Agent Platform
Usage: ...
```

---

## Phase 1 — Data Models (1 day)

**Goal:** All Pydantic models defined, importable, and covered by instantiation tests.

### Tasks

#### `models/financial.py`
- [ ] `CashPosition(currency, amount, account_id, as_of)`
- [ ] `CashFlowForecast(entity, periods, inflows, outflows, net)`
- [ ] `LiquidityMetrics(lcr, nsfr, hqla, net_outflows_30d)`
- [ ] `CoverageRatios(lcr_ratio, nsfr_ratio, lcr_compliant, nsfr_compliant)`
- [ ] `LiquidityGap(tenor_bucket, gap_amount, cumulative_gap)`
- [ ] `FXExposure(currency_pair, gross_long, gross_short, net, hedge_ratio)`
- [ ] `VaRMetrics(confidence, horizon_days, var_1d, var_10d, expected_shortfall)`
- [ ] `RateSensitivity(dv01, modified_duration, parallel_shift_impact)`
- [ ] `CounterpartyRisk(counterparty_id, gross_exposure, net_exposure, credit_rating)`
- [ ] `RiskSummary(total_fx_exposure, var_1d, top_risks: list[str])`
- [ ] `WorkingCapitalMetrics(dso, dpo, ccc, days_cash_on_hand)`
- [ ] `KPIScorecard(metrics: dict[str, KPIScore])`
- [ ] `StressTestResult(scenario_name, lcr_post_stress, shortfall, severity)`

#### `models/requests.py`
- [ ] `AgentRequest(session_id, request_id, user_query, context, scenario)`

#### `models/responses.py`
- [ ] `ResponseStatus(Enum)`: `COMPLETE | PENDING_APPROVAL | ERROR`
- [ ] `Recommendation(action, rationale, estimated_impact, requires_approval)`
- [ ] `AgentResponse(agent_id, request_id, status, reasoning, raw_llm_output)`
- [ ] Subclasses: `AtlasResponse`, `CoraResponse`, `TaraResponse`, `FiraResponse`, `AriaResponse`, `OrionResponse`

#### `models/audit.py`
- [ ] `EventType(Enum)`: `TOOL_CALL | TOOL_RESULT | AGENT_RESPONSE | APPROVAL_GATE | ALERT`
- [ ] `AuditEntry(timestamp, session_id, agent_id, event_type, payload)`
- [ ] `ToolCall(tool_name, inputs, call_id)`
- [ ] `ToolResult(call_id, output, duration_ms, error)`
- [ ] `ApprovalGate(recommendation_id, approved, approver_note, timestamp)`

### Tests
- Instantiate every model with valid data — assert no validation errors.
- Test Pydantic validation rejects invalid data (wrong types, negative amounts where prohibited).

---

## Phase 2 — Synthetic Data Layer (1 day)

**Goal:** Deterministic, configurable synthetic financial data available to all tools.

### Tasks

#### `data/synthetic_loader.py`
- [ ] `SyntheticDataLoader` class with `load_scenario(name: str)` method
- [ ] Returns a `TreasurySnapshot` — a frozen dataclass holding all synthetic data for one scenario
- [ ] Covers: cash positions, portfolio, FX book, payment schedule, counterparty list, rate curves

#### `data/scenarios/base_case.yaml`
- [ ] 3 entities (HoldCo, OpCo A, OpCo B)
- [ ] 5 currencies (USD, EUR, GBP, JPY, CHF)
- [ ] 10 investment positions
- [ ] 30-day payment schedule (inflows + outflows)
- [ ] 5 counterparties
- [ ] LCR ≈ 140% (healthy)

#### `data/scenarios/liquidity_stress.yaml`
- [ ] Same structure as base_case but with 30% outflow shock
- [ ] LCR ≈ 108% (near-breach territory)

#### `data/scenarios/fx_shock.yaml`
- [ ] EUR/USD moves -8%; GBP/USD moves -5%
- [ ] Triggers FX-001 alert

### Tests
- Load each scenario; assert `TreasurySnapshot` is populated and all expected keys present.
- Assert LCR in `liquidity_stress` is lower than `base_case`.

---

## Phase 3 — Financial Tools (2 days)

**Goal:** All deterministic calculation tools implemented and fully unit-tested. This is the most critical phase — correctness here underpins all agent outputs.

### `tools/liquidity.py`
- [ ] `get_cash_position(snapshot) → list[CashPosition]`
- [ ] `calculate_lcr(hqla, net_outflows_30d) → LCRResult`
- [ ] `calculate_nsfr(available_stable_funding, required_stable_funding) → NSFRResult`
- [ ] `calculate_liquidity_gap(cash_flows_by_tenor) → list[LiquidityGap]`
- [ ] `get_investment_portfolio(snapshot) → InvestmentPortfolio`
- [ ] `run_liquidity_stress(snapshot, outflow_shock_pct) → StressTestResult`
- [ ] `calculate_concentration_risk(positions) → ConcentrationRisk`

### `tools/cash_flow.py`
- [ ] `get_cash_flow_forecast(snapshot, horizon_days) → CashFlowForecast`
- [ ] `calculate_net_cash_position(snapshot) → CashPosition`
- [ ] `analyse_payment_patterns(snapshot) → PaymentPatternAnalysis`
- [ ] `calculate_working_capital_metrics(snapshot) → WorkingCapitalMetrics`
- [ ] `detect_anomalies(time_series, z_threshold) → list[CashAnomaly]`
- [ ] `calculate_sweep_opportunity(positions) → list[SweepOpportunity]`
- [ ] `calculate_forecast_variance(actual, forecast) → ForecastVariance`

### `tools/risk.py`
- [ ] `calculate_fx_exposure(snapshot) → list[FXExposure]`
- [ ] `calculate_var(returns, confidence, horizon_days) → VaRMetrics`
- [ ] `calculate_duration(cash_flows, discount_rates) → DurationResult`
- [ ] `calculate_hedge_effectiveness(hedged, unhedged) → HedgeEffectiveness`
- [ ] `run_scenario_analysis(snapshot, scenario_params) → list[ScenarioResult]`
- [ ] `calculate_counterparty_exposure(snapshot) → list[CounterpartyRisk]`
- [ ] `calculate_interest_rate_sensitivity(portfolio, rate_shock_bps) → RateSensitivity`

### `tools/analytics.py`
- [ ] `calculate_kpi_scores(metrics, targets) → KPIScorecard`
- [ ] `calculate_trend(time_series) → TrendResult`
- [ ] `benchmark_metrics(metrics, peer_set) → BenchmarkResult`
- [ ] `calculate_variance_analysis(actual, budget) → VarianceAnalysis`
- [ ] `generate_period_summary(snapshots, start, end) → PeriodSummary`
- [ ] `rank_priorities(issues, weights) → list[PriorityIssue]`

### `tools/alerts.py`
- [ ] `evaluate_alert_rules(snapshot, rules) → list[AlertBreach]`
- [ ] `classify_alert_severity(breach) → AlertSeverity`
- [ ] `get_alert_history(log_path) → list[AlertEvent]`
- [ ] `check_threshold(value, threshold, direction) → ThresholdResult`
- [ ] `calculate_breach_magnitude(value, threshold) → BreachMagnitude`

### `core/tool_registry.py`
- [ ] `ToolRegistry` — maps tool name strings to Python functions
- [ ] `@tool` decorator that registers a function and auto-generates its Anthropic tool schema from type hints and docstring
- [ ] `get_tool_schema(name) → dict` — returns Anthropic-format tool JSON
- [ ] `dispatch(name, kwargs) → any` — calls the registered function

### Tests (Phase 3 is most heavily tested)
- Unit test every tool function: valid inputs → correct output.
- Test boundary conditions: zero values, negative values, empty lists.
- Test `ToolError` raised on invalid inputs.
- Test `ToolRegistry` registration and dispatch.
- **Target: 100% line coverage on `tools/`.**

---

## Phase 4 — Core Infrastructure (½ day)

**Goal:** LLM client and audit logger ready for agent use.

### Tasks

#### `core/llm_client.py`
- [ ] `LLMClient` with `complete(messages, tools, system, max_tokens) → LLMResponse`
- [ ] `LLMResponse` dataclass: `content, stop_reason, tool_calls, usage`
- [ ] Handles tool-use stop reason — extracts tool call list
- [ ] `MockLLMClient` for testing — returns scripted responses from fixtures

#### `core/audit.py`
- [ ] `AuditLogger(session_id, audit_dir)` — creates `audit/run_<ts>_<session>.jsonl`
- [ ] `log(entry: AuditEntry) → None` — appends serialised entry, flushes immediately
- [ ] `read_session(session_id) → list[AuditEntry]` — for tests and review
- [ ] Thread-safe append (file lock)

### Tests
- `MockLLMClient` returns a scripted tool call; assert parsed correctly.
- `AuditLogger` writes entries; assert JSONL file created and parseable.
- Assert audit file is append-only (no in-place edits in public API).

---

## Phase 5 — Specialist Agents (2 days)

**Goal:** ATLAS, CORA, TARA, FIRA, ARIA each implemented and integration-tested.

Build order: ATLAS → CORA → TARA → FIRA → ARIA (simplest to most different).

### Per-agent tasks
For each of the five specialist agents:
- [ ] Write the agent class inheriting `BaseAgent`
- [ ] Define the fixed system prompt constant
- [ ] Define the tool list (subset of registry)
- [ ] Implement the `run()` agentic loop: send → handle tool use → iterate → return
- [ ] Map LLM output to the typed response model
- [ ] Write integration test using `MockLLMClient`

### Integration Tests (per agent)
- Happy path: mock LLM calls two tools, returns a recommendation → assert response model populated, audit log written.
- Error path: tool raises `ToolError` → assert agent returns `status=ERROR` and logs the failure.
- Approval gate: recommendation includes consequential action → assert `status=PENDING_APPROVAL`.

---

## Phase 6 — ORION Orchestrator (1 day)

**Goal:** ORION routes requests to specialists, aggregates, enforces approval gates.

### Tasks
- [ ] `agents/orion.py` — `OrionAgent` class
- [ ] `_classify_intent(query) → list[str]` — returns agent IDs to invoke
- [ ] `_invoke_specialists(agent_ids, request) → dict[str, AgentResponse]`
- [ ] `_synthesise(responses) → OrionResponse` — calls LLM to merge specialist summaries
- [ ] Approval gate propagation: if any specialist returns `PENDING_APPROVAL`, ORION response is `PENDING_APPROVAL`

### Integration Tests
- Daily briefing workflow: assert ATLAS, CORA, FIRA are invoked; result is `COMPLETE`.
- Liquidity stress: assert ATLAS (stress), TARA are invoked; result contains stress results.
- Approval gate: ATLAS returns `PENDING_APPROVAL`; assert ORION propagates.
- Unknown intent: ORION routes to FIRA for general query.

---

## Phase 7 — CLI & Demo (1 day)

**Goal:** The project runs interactively and demonstrates all major workflows.

### Tasks

#### `main.py`
- [ ] Rich-formatted interactive CLI
- [ ] Commands: `brief`, `stress-test`, `risk-review`, `alerts`, `ask <question>`, `quit`
- [ ] Display: coloured panels per agent, approval gate prompt, audit log path
- [ ] `--scenario` flag to select data scenario

#### `scripts/demo.py`
- [ ] Scripted end-to-end demo: runs all 5 main workflows in sequence
- [ ] Prints formatted output for each
- [ ] Saves audit log; prints path at end
- [ ] `--scenario` flag

### Sample CLI session
```
TreasuryAI > brief
[ORION] Generating daily treasury briefing...
[ATLAS] LCR: 142.3% ✅  NSFR: 118.7% ✅
[CORA]  Net cash position: $24.3M  Forecast (7d): +$2.1M
[FIRA]  Performance: 3 KPIs above target, 1 below (DPO)

[ORION] Daily Briefing: Treasury position is healthy...

TreasuryAI > stress-test
[ATLAS] Running 30% outflow stress...
⚠️  LCR drops to 107.4% — near regulatory minimum
[TARA]  VaR (1d, 95%): $1.2M  Top risk: EUR/USD exposure

[ORION] ⚠️ PENDING APPROVAL: Recommend liquidity buffer increase of $15M
Approve? (yes/no): 
```

---

## Phase 8 — Testing Completion & Documentation (½ day)

**Goal:** Full test coverage, documented README, project ready to share.

### Tasks
- [ ] Achieve ≥ 90% overall test coverage (100% on `tools/`)
- [ ] `pytest --cov` passes cleanly
- [ ] `README.md` complete: overview, architecture diagram, install, run, test instructions
- [ ] Code comments on all public functions and classes
- [ ] Final review: no hardcoded secrets, no live API calls in tests, all synthetic

---

## Dependency Summary

```
anthropic>=0.40.0        # LLM API
pydantic>=2.0            # Data models
pyyaml>=6.0              # Scenario files
rich>=13.0               # CLI formatting
pytest>=8.0              # Test framework
pytest-cov>=5.0          # Coverage reporting
python-dotenv>=1.0       # .env file loading
```

No database, no web framework, no message broker. The application is a Python process.

---

## Timeline (Solo Developer Estimate)

| Phase | Duration | Cumulative |
|-------|----------|------------|
| 0 — Scaffolding | ½ day | ½ day |
| 1 — Data Models | 1 day | 1.5 days |
| 2 — Synthetic Data | 1 day | 2.5 days |
| 3 — Financial Tools | 2 days | 4.5 days |
| 4 — Core Infrastructure | ½ day | 5 days |
| 5 — Specialist Agents | 2 days | 7 days |
| 6 — ORION | 1 day | 8 days |
| 7 — CLI & Demo | 1 day | 9 days |
| 8 — Polish & Docs | ½ day | 9.5 days |

**Total: ~10 working days** for a complete, portfolio-ready project.

---

## Testing Strategy

### Layers

```
tools/          → pure unit tests; no mocks; deterministic
models/         → instantiation + validation tests
core/audit.py   → file I/O integration tests
core/llm_client → unit tests with MockLLMClient
agents/         → integration tests with MockLLMClient + real tools
workflows/      → end-to-end tests with scripted LLM responses
```

### Coverage Targets
| Module | Target |
|--------|--------|
| `tools/` | 100% |
| `models/` | 100% |
| `core/` | ≥ 90% |
| `agents/` | ≥ 85% |
| `data/` | ≥ 80% |

### No LLM calls in tests
All agent tests use `MockLLMClient` which returns scripted responses from fixtures in `tests/fixtures/`. This keeps tests fast, deterministic, and free of API costs.

### Test Fixtures
`tests/fixtures/` contains:
- Per-agent scripted LLM conversations (tool calls + final response)
- Expected `AgentResponse` JSON for each workflow
- Synthetic data snapshots for tool tests
