# Phase 3 — Financial Tools

**Goal:** all deterministic calculation tools implemented and fully
unit-tested — the most critical phase, since correctness here underpins
every agent output (ADR-001).
**Status:** Complete — 209 tests total, **100% line coverage project-wide**
(`tools/`, `models/`, `data/`, and `core/` all at 100%; the plan's target was
100% on `tools/`/`models/`, ≥90% on `core/`, ≥80% on `data/` — all exceeded).

## What was built

- **`core/tool_registry.py`** — `ToolRegistry`, the `@tool` decorator,
  `get_tool_schema()`, `dispatch()`, and `ToolError`. Schema generation walks
  each function's type hints: `Decimal → {"type": "string"}` (so the LLM
  passes amounts as exact strings, never a float — the same ADR-003
  reasoning as `ExactDecimal`), enums → `{"type": "string", "enum": [...]}`,
  `list[X]`/`dict[K,V]` handled recursively. A parameter whose type isn't
  JSON-representable (`TreasurySnapshot`, `list[InvestmentPosition]`) is
  **excluded from the generated schema** rather than guessed at — those
  values are always supplied by the calling agent code from already-loaded
  data, never invented by the LLM, so they have no business being something
  the model fills in.
- **`tools/liquidity.py`** (7 functions), **`tools/cash_flow.py`** (7),
  **`tools/risk.py`** (7), **`tools/analytics.py`** (6), **`tools/alerts.py`**
  (5) — 32 functions total, every one decorated `@tool`, raising `ToolError`
  on invalid input, importable in one shot via `import tools`.

## Three real bugs caught and fixed during implementation

These weren't planned refactors — each surfaced because a test's actual
output looked financially wrong when checked against the real numbers, and
was worth stopping to fix in the tool logic rather than adjusting the test
to match.

1. **Currency blending in `calculate_concentration_risk`.** First draft
   summed `market_value` across all positions regardless of currency,
   producing a 92.7% "concentration" for CP-002 — because it silently added
   JPY 199,500,000 (a commercial paper face amount) to USD 2,000,000 (an MMF
   position) as if they were the same unit. There's no FX spot-rate table in
   this project's synthetic data (only a yield curve), so real conversion
   isn't possible without inventing numbers. Fixed by computing concentration
   **separately within each currency** (`ConcentrationRisk.by_currency`)
   rather than blending — the same reasoning `get_investment_portfolio`
   already used for its per-currency totals.
2. **The same bug in `calculate_counterparty_exposure`.** Fixed the same
   way, but this one required touching the Phase-1-locked `CounterpartyRisk`
   model: added an optional `currency: CurrencyCode | None = None` field
   (backward-compatible — existing instantiations without it still validate)
   so the function can emit one row per (counterparty, currency) pair
   instead of one blended row per counterparty.
3. **A sign bug in `classify_alert_severity`.** The first version took a
   bare `BreachMagnitude` and treated `relative_pct <= 0` as "not breached."
   That's only true for an `ABOVE`-direction threshold (FX exposure, DV01).
   For a `BELOW`-direction threshold (LCR falling under 110%), an actual
   breach produces a *negative* `relative_pct` — so the bug would have
   classified real critical breaches as `INFO`. Fixed by having the function
   take the direction-aware `ThresholdResult` from `check_threshold`
   instead, which already has a correctly-computed `breached` flag.

## Documented simplifications (portfolio project, not a production risk engine)

- **No FX spot-rate conversion anywhere.** `get_cash_flow_forecast` and
  `calculate_net_cash_position` consolidate the USD-denominated subset of
  multi-currency data only, rather than silently blending currencies (same
  principle as the bugs above, applied proactively this time).
- **`calculate_var`** is historical simulation only, scaled between 1-day
  and 10-day via square-root-of-time — no parametric or Monte Carlo VaR.
- **`calculate_duration` / `calculate_interest_rate_sensitivity`** approximate
  a bullet instrument's modified duration with its time to maturity, since
  the synthetic data models face value + coupon + maturity date, not a full
  intermediate cash-flow schedule a real duration calc needs.
- **`calculate_hedge_effectiveness`** is a notional-ratio proxy
  (hedged / (hedged + unhedged)), not the dollar-offset regression method
  ASC 815 / IFRS 9 actually require — there's no hedge-item vs.
  hedging-instrument P&L history in the synthetic data to regress.
- **`calculate_working_capital_metrics`**: CCC = DSO - DPO with no DIO term
  (no inventory is modelled — this is a treasury/holding group, not a
  manufacturer).

## Phase 2 data layer extended (documented, not silent)

`calculate_working_capital_metrics` needs DSO/DPO/CCC inputs no amount of
position-level data can derive (no AR/AP ledger or income statement exists
in the synthetic data). Added four scenario-level scalars to
`TreasurySnapshot` and all three scenario YAMLs — `annual_revenue`,
`annual_cogs`, `accounts_receivable`, `accounts_payable` — following the
same pattern already established for `hqla` / `net_cash_outflows_30d` in
Phase 2. `data/synthetic_loader.py`'s module docstring and
`phases/PHASE_2_SYNTHETIC_DATA_LAYER.md` were updated accordingly.

## Verify

```bash
pytest tests/ --cov=models --cov=data --cov=tools --cov=core --cov-report=term-missing
```

```python
import tools
from core.tool_registry import default_registry
print(len(default_registry.list_tools()))  # 32
```

Cross-check: `tools.liquidity.run_liquidity_stress(base_case_snapshot,
Decimal("0.30"))` independently reproduces the exact 107.7% LCR hand-computed
into `data/scenarios/liquidity_stress.yaml` in Phase 2 — the tool logic and
the scenario data agree.
