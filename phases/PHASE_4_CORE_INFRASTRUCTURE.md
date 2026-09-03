# Phase 4 — Core Infrastructure

**Goal:** LLM client and audit logger ready for agent use.
**Status:** Complete — 227 tests total, 100% line coverage project-wide.

## What was built

### `core/llm_client.py`

- **`LLMResponse`** (frozen dataclass): `content`, `stop_reason`, `tool_calls`
  (`list[ToolCallRequest]`), `usage` (`dict[str, int]`).
- **`ToolCallRequest`** (frozen dataclass): `id`, `name`, `input`.
- **`LLMClient`** — thin wrapper around `anthropic.Anthropic().messages.create()`.
  Parses the response's content blocks: `type == "text"` blocks are joined
  into `LLMResponse.content`; `type == "tool_use"` blocks become
  `ToolCallRequest`s. Reads its model and API key from `core.config.get_settings()`
  by default, so it's the caller's choice whether to override either. Raises
  the same `RuntimeError` as `Settings.require_api_key()` if no API key is
  configured.
- **`MockLLMClient`** — scripted responses returned in order, one per
  `complete()` call, regardless of what's actually passed in. Tracks every
  call it received (`received_calls`) so tests can assert on what an agent
  sent. `MockLLMClient.from_fixture(path)` loads a JSON fixture (a list of
  `{content, stop_reason, tool_calls, usage}` objects) — see
  `tests/fixtures/sample_llm_responses.json` for the shape agents' fixture
  files in Phase 5 will follow.

**Testing `LLMClient` without live API calls (ADR-011).** Rather than skip
coverage on the real client, its tests monkeypatch `anthropic.Anthropic`
with a fake object shaped like the real SDK's response (`SimpleNamespace`
content blocks, `stop_reason`, `usage`), so the actual parsing logic —
joining text blocks, extracting tool-use blocks, mapping usage — is
exercised and covered without a network call or API key. Only
`MockLLMClient` is meant to be used inside agent/workflow tests; `LLMClient`
itself is exercised here purely to prove its parsing is correct.

### `core/audit.py`

- **`AuditLogger(session_id, audit_dir)`** — creates
  `<audit_dir>/run_<UTC timestamp to the microsecond>_<session_id>.jsonl` on
  construction (directory created if missing).
- **`log(entry: AuditEntry) -> None`** — serialises via `entry.model_dump_json()`,
  appends a line, flushes and `os.fsync()`s immediately (durable write, not
  buffered). Rejects (raises `ValueError`) an entry whose `session_id`
  doesn't match the logger's own — a logger is scoped to one session, so a
  mismatched entry is almost certainly a caller bug, not something to log
  silently. Writes are guarded by a `threading.Lock` for the "thread-safe
  append" requirement in the plan.
- **`read_session(session_id) -> list[AuditEntry]`** — globs
  `run_*_<session_id>.jsonl` in `audit_dir` and parses every line back into
  an `AuditEntry`, across however many run files share that session_id.
- **No delete or update method exists** (ADR-004) — verified by a test that
  introspects `AuditLogger`'s public methods and asserts the set is exactly
  `{log, read_session}`.

## Verify

```bash
pytest tests/unit/test_llm_client.py tests/unit/test_audit.py -v --cov=core.llm_client --cov=core.audit --cov-report=term-missing
```

```bash
pytest tests/ --cov=models --cov=data --cov=tools --cov=core --cov-report=term-missing
# 227 passed, 100% across models/, data/, tools/, core/
```
