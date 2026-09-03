# Phase 6 — ORION Orchestrator

**Goal:** ORION routes requests to specialists, aggregates, enforces approval gates.
**Status:** Complete — 300 tests total, 100% line coverage project-wide.

## Why `OrionAgent` doesn't subclass `BaseAgent`

Every specialist agent is built around `BaseAgent.run()`'s tool-use loop:
send a message, dispatch whatever `tools/*.py` functions the model calls,
feed results back, repeat until `end_turn`. ORION doesn't have that shape.
Per agent-specifications.md, `route_to_agent` is explicitly *"an internal
routing call (not an LLM tool; handled in code)"* — intent classification
and specialist selection are deterministic Python, never something the
model chooses via tool-calling. Only `summarise_responses` is described as
an actual LLM tool, and even that turned out not to need the tool-call
machinery: producing a paragraph of prose doesn't need a JSON schema to
validate against, unlike `submit_recommendation` (Phase 5), which exists
specifically because `Recommendation` *is* structured data. So ORION's
`_synthesise()` makes one plain (non-tool-use) `llm_client.complete()` call
over the specialists' own `reasoning` text, and `OrionAgent` is its own
small class rather than a `BaseAgent` subclass carrying a tool loop it would
never use.

## What was built

- **`_classify_intent(query) -> list[str]`** — a keyword-routing table
  covering all four documented workflows (Daily Briefing -> ATLAS+CORA+FIRA,
  Liquidity Stress -> ATLAS+TARA, FX Risk Review -> TARA+FIRA, single-
  specialist ad-hoc queries -> ATLAS/CORA/TARA/FIRA individually) plus an
  explicit fallback to FIRA for anything unrecognised (the plan's "Unknown
  intent: ORION routes to FIRA for general query" test). The table only ever
  names ATLAS/CORA/TARA/FIRA — **ARIA never appears**, structurally enforcing
  the spec's "ORION must not invoke ARIA directly" boundary rather than
  relying on convention. `test_classify_intent_never_routes_to_aria` checks
  this holds across every query the other tests exercise.
- **`_invoke_specialists(agent_ids, request) -> dict[str, AgentResponse]`** —
  calls `.run(request)` on each already-constructed specialist instance
  (each specialist keeps whatever `llm_client`/`audit_logger`/`snapshot` it
  was built with; ORION only holds references to them).
- **`_synthesise(request, responses) -> OrionResponse`** — builds the final
  briefing from one LLM call over the specialists' `reasoning` text.
  Status precedence: any specialist `ERROR` -> `ERROR`; else any
  `PENDING_APPROVAL` -> `PENDING_APPROVAL`; else `COMPLETE`.
  `recommendations` flattens every specialist's `.recommendations` (skipping
  FIRA/ARIA, which don't have that field, via `getattr(..., None) or []`).
  If no specialist ran at all (empty routing, or every requested specialist
  missing from `self.specialists`), the response is `ERROR` with an explicit
  "no specialist was available" message rather than silently returning an
  empty-but-COMPLETE briefing.
- **`triage_alert(triage_request, request) -> OrionResponse`** — the
  ARIA -> ORION direction from the Agent Interaction Matrix: routes directly
  to `triage_request.recommended_agent` (a single specialist), bypassing
  `_classify_intent` entirely, since ARIA already decided who should look at
  it.
- **`last_specialist_responses`** — a plain instance attribute (not part of
  `OrionResponse`, which only carries `specialist_summaries: dict[str, str]`)
  holding the raw `AgentResponse` objects from the most recent `run()`, for
  tests or a future UI that need e.g. `AtlasResponse.stress_results` directly
  rather than its one-paragraph summary.
- **Audit trail unification**: every specialist ORION invokes shares the
  *same* `AuditLogger` instance (same `session_id`), so a full ORION-driven
  session — every specialist's `TOOL_CALL`/`TOOL_RESULT`/`AGENT_RESPONSE`
  plus ORION's own final `AGENT_RESPONSE` — lands in one JSONL file, exactly
  matching "own the audit log lifecycle" from the spec's ORION
  responsibilities.

## Verify

```bash
pytest tests/integration/test_orion_agent.py tests/unit/test_orion_classify_intent.py -v
pytest tests/ --cov=models --cov=data --cov=tools --cov=core --cov=agents --cov-report=term-missing
# 300 passed, 100% across every package
```
