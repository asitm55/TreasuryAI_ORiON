# Phase 1 — Data Models

**Goal:** all Pydantic models defined, importable, and covered by instantiation tests.
**Status:** Complete — 52 tests, 100% line coverage on `models/`.

## What was built

- **`models/base.py`** (not in the original plan, added to satisfy ADR-003) —
  `TreasuryBaseModel` and `ExactDecimal`, an `Annotated[Decimal, ...]` type
  that serialises to a JSON **string**, not a float. Pydantic v2's default
  JSON mode converts `Decimal` to `float`, which would silently reintroduce
  the rounding error ADR-003 exists to prevent. Verified:
  `Decimal("1250000.10")` round-trips as `"1250000.10"`, not `1250000.1`.
- **`models/financial.py`** — the 13 models listed in the plan
  (`CashPosition`, `CashFlowForecast`, `LiquidityMetrics`, `CoverageRatios`,
  `LiquidityGap`, `FXExposure`, `VaRMetrics`, `RateSensitivity`,
  `CounterpartyRisk`, `RiskSummary`, `WorkingCapitalMetrics`,
  `KPIScorecard`, `StressTestResult`), plus 9 supporting types the plan's
  bullet list didn't name but that `agent-specifications.md` requires as
  fields on the per-agent response models: `CashAnomaly`,
  `SweepOpportunity`, `ScenarioResult`, `TrendInsight`, `BenchmarkResult`,
  `PriorityIssue`, `AlertEvent`, `TriageRequest`, `KPIScore`. Without these,
  `responses.py` would not type-check.
- **`models/requests.py`** — `AgentRequest`.
- **`models/responses.py`** — `ResponseStatus`, `Recommendation`,
  `AgentResponse`, and the six subclasses: `AtlasResponse`, `CoraResponse`,
  `TaraResponse`, `FiraResponse`, `AriaResponse`, `OrionResponse`.
- **`models/audit.py`** — `EventType`, `AuditEntry`, `ToolCall`,
  `ToolResult`, `ApprovalGate` per ADR-004.

## Domain validation added beyond bare type hints

- 3-letter ISO currency codes (`CurrencyCode`), `CCY/CCY` pair pattern
  (`CurrencyPair`), S&P-style credit rating pattern (`CreditRating`).
- Ratios represented as fractions, not percentages (`1.42` = 142%);
  `hedge_ratio` and `confidence` bounded to `[0,1]` / `(0,1)`.
- Non-negative exposures, HQLA, and VaR fields.
- `CashFlowForecast` cross-field check: `periods`, `inflows`, `outflows`,
  and `net` must all be the same length.

## Verify

```bash
pytest tests/unit/test_models_financial.py tests/unit/test_models_requests.py \
       tests/unit/test_models_responses.py tests/unit/test_models_audit.py \
       -v --cov=models --cov-report=term-missing
```
