# Phase 7 — CLI & Demo

**Goal:** the project runs interactively and demonstrates all major workflows.
**Status:** Complete — 335 tests total, 99% line coverage project-wide (the
only two uncovered lines are the standard `if __name__ == "__main__":`
guards in `main.py` and `scripts/demo.py`, each exercised by a subprocess
test but invisible to the in-process coverage instrumentation).

## A real gap found before the CLI could even work: agents had no idea what the actual numbers were

Every specialist agent's `run()` loop only ever sent `request.user_query` as
the first message — nothing about the current LCR, NSFR, FX book, or
anything else. That's invisible with `MockLLMClient`, which ignores message
content entirely and just returns whatever was scripted — exactly how
Phase 5/6's tests worked. But it means a *real* LLM, given only "run a
liquidity stress test," would have no way to know `hqla` or
`net_cash_outflows_30d` to call `calculate_lcr` with. This is Phase 7's
actual goal ("the project runs interactively") surfacing a real bug that
every prior phase's mocked tests structurally couldn't catch.

Fixed by adding a `_build_context(request, tool_results) -> str | None` hook
to `agents/base.py`'s `BaseAgent`, called once at the start of `run()` and
prepended to the first message. Default: `None` (most agents don't need
it — CORA/TARA/FIRA's tools work fine from `snapshot` injection alone or
take fully caller-supplied data). Two agents override it:

- **ATLAS** — plain text: reports `hqla`, `net_cash_outflows_30d`,
  `available_stable_funding`, `required_stable_funding` straight from the
  snapshot. Not a calculation, just telling the model what it's working
  with.
- **ARIA** — the more interesting case. `evaluate_alert_rules(metrics, ...)`
  takes metric *values* as input; it doesn't compute them. Rather than have
  the model guess or hallucinate a current LCR, `AriaAgent._build_context`
  dispatches `calculate_lcr`/`calculate_nsfr` itself, through the exact same
  `self._dispatch_all()` path any tool call goes through — so these are
  real, audited `TOOL_CALL`/`TOOL_RESULT` entries, not numbers computed
  outside the trail. This changed ARIA's tool-call count (2 extra calls
  before the LLM ever responds), which broke two Phase 5 test assertions —
  fixed by updating the expected counts, not by reverting the fix.

**TARA's `calculate_var`/`calculate_duration`/`calculate_hedge_effectiveness`
remain a documented, un-fixed limitation**: they need a historical returns
series, cash-flow schedule, or hedge/unhedged amounts this project's
synthetic data doesn't model (there's no historical P&L time series
anywhere in `TreasurySnapshot`). Rather than fabricate one, TARA's system
prompt now explicitly tells the model not to call those three tools unless
the operator supplies the data in conversation — an honest scope boundary,
not a silently broken feature.

## What was built

### `main.py`

- **`TreasurySession`** — wires all five specialists + ORION behind one
  shared `AuditLogger`/`TreasurySnapshot`. `llm_client_factory: Callable[[str],
  Any]` is the dependency-injection point: production code leaves it `None`
  (defaults to `lambda agent_id: LLMClient()`, the real Anthropic-backed
  client from Phase 4); every test substitutes a per-agent `MockLLMClient`.
- **Five commands** — `brief`, `stress-test`, `risk-review` (all three
  route through ORION), `alerts` (calls `AriaAgent` **directly**, not
  through ORION — matching the spec's "ORION must not invoke ARIA
  directly"), and `ask <question>`.
- **Two run modes**: `python main.py <command>` for one-shot execution,
  or `python main.py` alone for the interactive REPL matching the plan's
  sample session (`TreasuryAI > brief`, ..., `TreasuryAI > quit`). Both
  funnel through the same `dispatch_command()`.
- **Approval gate**: `_prompt_approval()` renders each
  `PENDING_APPROVAL` recommendation in a panel and asks
  `rich.prompt.Confirm.ask("Approve?")`. Per ADR-006, the decision is
  logged as an `ApprovalGate` audit entry either way — **nothing is ever
  executed**, approved or not; the CLI only prints and logs. `auto_decline_approval=True`
  (used by `scripts/demo.py`) skips the interactive prompt and logs a
  rejection, so a scripted run never blocks on stdin.
- **Rich formatting**: colour-coded `[AGENT]` tags, a `Panel` for the final
  briefing and for pending recommendations, a `Table` for alerts.

### `scripts/demo.py`

- **`run_demo(scenario, console, llm_client_factory=None)`** — runs all
  five workflows in sequence (brief, stress-test, risk-review, alerts, an
  ad-hoc `ask` question) against one `TreasurySession`, auto-declining any
  approval gate so it never blocks. Reuses `main.dispatch_command()`
  directly rather than duplicating rendering/approval logic.
  `--scenario` selects the data scenario; prints the audit log path at the
  end.

## A second real bug, also only visible once this ran for real

`_render_orion_response`'s panel title used an em dash, and the
pending-approval/error indicators used Rich's `:warning:`/`:x:` emoji
shortcodes. Both crashed with `UnicodeEncodeError: 'charmap' codec can't
encode character...` the first time this actually ran in this environment's
legacy Windows console (cp1252) — the same class of bug Phase 0 hit once
already with the banner's em dash, but this time from Rich's own emoji
rendering, not a literal character I'd typed. Given ADR-10's "runs on any OS
with Python 3.11+," relying on Unicode symbols that can crash a legacy
Windows terminal isn't acceptable — replaced with plain ASCII (`[!]`,
`[x]`, `-`) everywhere in `main.py`'s user-facing output.

## Honest limitation: no live API key in this environment

Everything above was verified with `MockLLMClient` — the full CLI pipeline
(command routing, rendering, audit logging, the approval-gate flow, both
run modes) runs correctly end-to-end. What I could **not** do is run
`python main.py brief` (or `scripts/demo.py`) against the real Anthropic
API, because this environment has no `ANTHROPIC_API_KEY` configured. That
gap is narrowed by two things built specifically to reduce it: Phase 4's
`LLMClient` tests, which verify its request/response parsing against a
faked SDK response shape (not just mocked at the `LLMClient` level), and
this phase's `_build_context` fix, which exists precisely because a real
model — unlike `MockLLMClient` — actually reads the prompt. But the literal
"does a real Claude call successfully drive `calculate_lcr` end-to-end"
question needs a live key to confirm, and that's a manual verification step
for whoever runs this with real credentials, not something I can claim to
have done.

## Verify

```bash
python main.py --help
python main.py quit                      # no API key needed
python scripts/demo.py --help            # no API key needed

# with a real ANTHROPIC_API_KEY configured:
python main.py brief
python main.py                           # interactive REPL
python scripts/demo.py --scenario liquidity_stress

pytest tests/integration/test_main_cli.py tests/integration/test_demo_script.py -v
pytest tests/ --cov=models --cov=data --cov=tools --cov=core --cov=agents --cov=main --cov=scripts.demo --cov-report=term-missing
# 335 passed, 99% (only the two subprocess-only __main__ guards)
```
