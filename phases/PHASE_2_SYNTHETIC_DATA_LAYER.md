# Phase 2 — Synthetic Data Layer

**Goal:** deterministic, configurable synthetic financial data available to
all tools.
**Status:** Complete — 16 new tests (68 total), 100% line coverage on `data/`
and `models/`.

## What was built

### `data/synthetic_loader.py`

- `SyntheticDataLoader.load_scenario(name)` reads
  `data/scenarios/<name>.yaml`, validates every section against a typed
  Pydantic model, and returns an immutable `TreasurySnapshot`
  (`@dataclass(frozen=True)`, tuple-valued collections so nothing downstream
  can mutate loaded data).
- `SyntheticDataLoader.list_scenarios()` — utility for discoverability
  (used by `ScenarioNotFoundError` to list what's actually available).
- Two typed exceptions: `ScenarioNotFoundError` (bad scenario name — message
  lists what's available) and `SyntheticDataError` (a YAML section fails
  Pydantic validation — message names the offending section and scenario).
- New Pydantic models scoped to this file, distinct from `models/financial.py`
  (which holds *tool-output* types, not raw source data):
  `InvestmentPosition`, `FXBookEntry`, `PaymentScheduleEntry`,
  `CounterpartyProfile`, `RateCurvePoint`, `FXShockAssumption`, plus
  `FXDirection` and `CashFlowDirection` enums.

### Design decision: `hqla` / `net_cash_outflows_30d` / `available_stable_funding` / `required_stable_funding` are scenario-level scalars, not derived bottom-up

`architecture.md`'s tool signature is
`calculate_lcr(hqla: Decimal, net_cash_outflows_30d: Decimal) -> LCRResult` —
i.e. Phase 3's tool takes these two numbers directly, it doesn't derive them
from granular positions. Basel LCR/NSFR run-off rates and haircuts are
themselves calibration parameters, not something this project computes from
first principles. So `TreasurySnapshot` carries these four figures directly
from the YAML, decoupled from the granular cash / investment / FX / payment
data that feeds the *other* tools (cash flow forecasting, FX exposure, risk).
This was flagged rather than silently assumed, since the plan's Phase 2 test
("assert LCR in liquidity_stress is lower than base_case") only makes sense
once you decide where LCR's inputs come from.

### `CashPosition` doesn't carry an `entity` field

Phase 1 already fixed `CashPosition`'s fields to exactly
`(currency, amount, account_id, as_of)` — no `entity`. Rather than reopen an
already-tested Phase 1 contract, `TreasurySnapshot.cash_positions` is
`dict[str, tuple[CashPosition, ...]]` keyed by entity name; `account_id`
values are entity-prefixed (`HOLD-USD-01`, `OPA-USD-01`, `OPB-JPY-01`) for
readability.

### `data/scenarios/base_case.yaml`

3 entities (HoldCo, OpCo A, OpCo B) x 5 currencies (USD, EUR, GBP, JPY, CHF),
10 investment positions (T-bills, notes, gilts, bunds, corporate bonds,
commercial paper, MMF — mixed HQLA-eligible flags), a 4-position FX book, an
18-entry 30-day payment schedule (both directions, all three entities), 5
counterparties (AAA down to A), and a 35-point rate curve (7 tenors x 5
currencies).

**LCR = 52,500,000 / 37,500,000 = 1.400 (140.0%)** — matches the plan's
"LCR ≈ 140% (healthy)" exactly, not approximately.
**NSFR = 40,000,000 / 33,700,000 = 1.1869 (118.7%)**.

### `data/scenarios/liquidity_stress.yaml`

Identical structure to `base_case.yaml`. A 30% shock is applied to
`net_cash_outflows_30d` (37,500,000 → 48,750,000) **and**, for internal
consistency, to every scheduled `OUTFLOW` payment amount in the same
30-day schedule (inflows unchanged).

**LCR = 52,500,000 / 48,750,000 = 1.0769 (107.7%)** — matches "LCR ≈ 108%",
still Basel-compliant but near the regulatory minimum. NSFR is deliberately
left unchanged (118.7%): it's a 1-year structural funding metric, a 30-day
outflow shock shouldn't move it, and the test suite asserts this explicitly.

### `data/scenarios/fx_shock.yaml`

Same liquidity position as `base_case` (this scenario targets the FX book,
not funding). The FX book is enlarged and mostly unhedged: EUR/USD notional
raised from $5M (70% hedged in base_case) to **$12M, fully unhedged** —
breaching alert rule FX-001 (unhedged exposure > $10M → HIGH). GBP/USD is
similarly widened to $6M unhedged. A `scenario_shocks` block records the
named shock (EUR/USD -8%, GBP/USD -5%) for Phase 3's
`run_scenario_analysis` tool to consume; `base_case` and `liquidity_stress`
both have `scenario_shocks == ()`.

## Verify

```bash
pytest tests/unit/test_synthetic_loader.py -v --cov=data --cov-report=term-missing
```

```python
from data.synthetic_loader import SyntheticDataLoader
loader = SyntheticDataLoader()
for name in loader.list_scenarios():
    snap = loader.load_scenario(name)
    print(name, snap.hqla / snap.net_cash_outflows_30d)
```
