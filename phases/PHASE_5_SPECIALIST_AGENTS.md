# Phase 5 — Specialist Agents

**Goal:** ATLAS, CORA, TARA, FIRA, ARIA each implemented and integration-tested.
**Status:** Complete — 273 tests total, 100% line coverage project-wide.

This was the phase where everything built so far (models, synthetic data,
tools, registry, LLM client, audit logger) got wired together into an actual
agentic loop for the first time — and it's the phase that surfaced the most
real bugs, precisely because running the full path end-to-end exercises
interactions unit tests can't.

## Two design questions the plan doesn't answer, resolved before writing code

### 1. How do non-LLM-suppliable tool arguments get filled in?

Several tools take a `TreasurySnapshot` or a list of typed domain objects
(`list[InvestmentPosition]`, `list[CashPosition]`) that `core/tool_registry.py`
deliberately excludes from the LLM-facing schema (Phase 3's design: those
values are always supplied by the calling agent from already-loaded data,
never invented by the model). Each concrete agent now declares a
`tool_injections` map — `{tool_name: {param_name: resolver(agent, tool_results)}}`
— that `BaseAgent.run()` consults before every dispatch. Most resolvers are
trivial (`lambda agent, _: agent.snapshot`), but one is genuinely interesting:
ARIA's `classify_alert_severity` takes a `ThresholdResult` — the *output* of
a prior `check_threshold` call, which is just as unrepresentable in JSON as a
`TreasurySnapshot`. Its resolver pulls the agent's own last `check_threshold`
result rather than trusting the model to reconstruct it, the same
tool-output-chaining pattern used everywhere else, just with a prior tool
result as the source instead of static snapshot data.

### 2. How do agents produce a structured `Recommendation`?

`Recommendation` (action, rationale, estimated_impact, requires_approval) is
narrative judgment — no `tools/*.py` function computes one, because it isn't
a calculation. Rather than parse free text, `agents/base.py` defines
`submit_recommendation` as a tool in its own right (`action`, `rationale`,
`estimated_impact`, `requires_approval` — all plain JSON-representable
types), registered through the same `@tool`/schema/dispatch machinery as
every financial tool. ATLAS, CORA, and TARA list it; FIRA and ARIA don't,
because their response models (`FiraResponse`, `AriaResponse`) have no
`recommendations` field at all — matching agent-specifications.md exactly.
`BaseAgent.run()` collects every `submit_recommendation` call across the
conversation and sets `status = PENDING_APPROVAL` if any of them has
`requires_approval=True`.

## Three real bugs found by actually running the loop

Unit tests on `tools/` and `core/tool_registry.py` were 100% covered before
this phase — and still had two live bugs, because their test fixtures didn't
reproduce the real conditions. These only surfaced once an agent actually
called a real tool through the real dispatch path with LLM-shaped JSON input.

1. **Tools never got registered.** `AtlasAgent`'s first test run raised
   `ToolNotFoundError: 'get_cash_position' is not registered` — nothing had
   ever imported `tools.liquidity`, so its `@tool`-decorated functions never
   executed. Fixed by having each `agents/*.py` module import its
   corresponding `tools/*.py` module for the registration side effect, and
   `agents/__init__.py` import every agent module so `import agents` alone
   registers everything (33 tools: the 32 financial ones plus
   `submit_recommendation`).
2. **`from __future__ import annotations` broke every real tool's schema.**
   Every `tools/*.py` module (and `core/tool_registry.py` itself) uses PEP
   563 postponed evaluation, which stringifies type hints at runtime —
   `inspect.signature(calculate_lcr).parameters["hqla"].annotation` was the
   literal string `"Decimal"`, not the `Decimal` class. Phase 3's registry
   tests had 100% coverage but never caught this, because their test
   fixtures defined functions inline in the test file *without* that import,
   accidentally sidestepping the exact condition every real tool has.
   `get_tool_schema()` was silently generating **empty** `properties: {}`
   for every real tool — invisible until an agent actually tried to hand
   the schema to an LLM. Fixed by resolving annotations through
   `typing.get_type_hints(func)` instead of raw `Parameter.annotation`, in
   both schema generation and the new coercion step below.
3. **JSON strings never got converted back to `Decimal`/`date`/enums before
   dispatch.** The schema (correctly, per ADR-003) tells the LLM to send
   Decimal amounts as strings — but `dispatch()` was handing that string
   straight to `tools/liquidity.py` functions doing arithmetic on it,
   raising `TypeError: '<' not supported between instances of 'str' and
   'int'` the moment `calculate_lcr` compared `net_cash_outflows_30d` (a
   string) to `0`. Added `_coerce_value()` to `core/tool_registry.py` — the
   mirror image of the existing `_json_schema_for()` — which converts
   JSON-ish values back to `Decimal`, `date`, `datetime`, enum members, and
   recursively through `list`/`tuple`/`dict`, based on the same
   type-hint-resolution fix above.

All three are fixed in `core/tool_registry.py` and `agents/`, with dedicated
unit tests (not just incidental integration coverage) for the coercion
logic, the registration fix, and the schema-resolution fix — including a
regression test (`test_schema_and_dispatch_work_with_future_annotations_module`)
that specifically imports a real `tools/*.py` function to make sure this
exact bug can't come back unnoticed.

## Per-agent notes

- **ATLAS**: all 7 `tools/liquidity.py` functions + `submit_recommendation`.
  `LiquidityMetrics`/`CoverageRatios` are assembled from the `calculate_lcr`/
  `calculate_nsfr` tool results plus `snapshot.hqla`/`snapshot.net_cash_outflows_30d`
  directly (those two tools return only `{ratio, compliant}`, not the raw
  inputs — the snapshot already has them).
- **CORA**: all 7 `tools/cash_flow.py` functions + `submit_recommendation`.
  `CoraResponse` requires `forecast_30d`/`net_cash_position`/`working_capital`
  as non-optional fields; if the model doesn't call the corresponding tool,
  a documented zero-value fallback (`_empty_forecast()` etc.) is used rather
  than crashing response construction.
- **TARA**: all 7 `tools/risk.py` functions + `submit_recommendation`.
  `RiskSummary` (not itself a tool's return type) is assembled by the agent:
  `total_fx_exposure` sums `abs(net)` across FX exposures, `top_risks` lists
  the three largest by absolute net exposure — simple aggregation/formatting
  for presentation, not the kind of financial calculation ADR-001 reserves
  for tools.
- **FIRA**: all 6 `tools/analytics.py` functions, no `submit_recommendation`
  (no `recommendations` field on `FiraResponse`), `status` hardcoded to
  `COMPLETE` per spec. None of its tools take a `TreasurySnapshot` — KPI
  targets and peer benchmarks are policy inputs the caller supplies, not
  data the synthetic layer owns.
- **ARIA**: all 5 `tools/alerts.py` functions, no `submit_recommendation`
  (no `recommendations` field on `AriaResponse` either), `status` hardcoded
  to `COMPLETE`. `triage_requests` are built deterministically from a fixed
  metric → specialist lookup table (`lcr`/`nsfr` → ATLAS, `net_cash_position`
  → CORA, `unhedged_fx_exposure` → TARA, ...), not LLM judgment — matching
  the spec's "ARIA does not perform deep analysis, it checks thresholds."

## Verify

```bash
pytest tests/integration -v
pytest tests/ --cov=models --cov=data --cov=tools --cov=core --cov=agents --cov-report=term-missing
# 273 passed, 100% across every package
```
