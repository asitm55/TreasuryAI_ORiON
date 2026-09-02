# TreasuryAI — Architectural Decision Log

Each entry records a decision, its context, the options considered, and the rationale. This log is append-only.

---

## ADR-001: LLMs Must Not Perform Financial Calculations

**Status:** Accepted  
**Date:** 2026-08-24

### Context
LLMs are probabilistic systems. They can hallucinate numeric results, misapply formulas, or produce confidently wrong outputs for financial calculations. Treasury decisions depend on exact numbers — regulatory ratios, exposure amounts, VaR estimates.

### Decision
All arithmetic and financial calculations are implemented as deterministic Python functions in the `tools/` layer. LLMs are used only to:
- Select which tool to call and with what parameters.
- Interpret and explain tool results.
- Write narrative recommendations.

### Consequences
- Calculations are testable with 100% coverage and predictable outputs.
- Agent behaviour is auditable: every number in a response traces back to a tool call in the audit log.
- Increased implementation effort (must implement Python tools for every calculation).

---

## ADR-002: Pydantic for All Structured Data

**Status:** Accepted  
**Date:** 2026-08-25

### Context
Multi-agent systems pass data between components. Without strict typing, subtle bugs (wrong field names, missing values, wrong units) are hard to catch.

### Decision
All data crossing component boundaries — tool inputs/outputs, agent requests/responses, audit entries — is defined as Pydantic v2 models. Plain dicts and untyped returns are prohibited at boundaries.

### Consequences
- Validation errors are caught at the boundary, not silently propagated.
- Models serve as living documentation of data contracts.
- Pydantic v2 is a project dependency (acceptable: widely used, stable, fast).

---

## ADR-003: Monetary Values Use `Decimal`, Not `float`

**Status:** Accepted  
**Date:** 2026-08-26

### Context
IEEE 754 floating-point arithmetic introduces rounding errors that compound across financial calculations. For example, `0.1 + 0.2 != 0.3` in Python floats.

### Decision
All monetary amounts in `models/financial.py` and `tools/` use Python's `decimal.Decimal`. Pydantic fields for monetary values are typed as `Decimal` with explicit precision constraints.

### Consequences
- Calculations are mathematically exact for the precision used.
- Slightly more verbose code (Decimal arithmetic requires explicit constructors).
- JSON serialisation must convert Decimal to string or float — handled centrally in Pydantic model config.

---

## ADR-004: Append-Only JSONL Audit Log

**Status:** Accepted  
**Date:** 2026-08-27

### Context
Auditability is a core requirement. Every tool call and agent decision must be traceable. A database would add operational complexity; a mutable file could be edited.

### Decision
Audit events are written as newline-delimited JSON (JSONL) to a file in `audit/`. Each entry is immediately flushed to disk. The `AuditLogger` public API has no "delete" or "update" method.

### Alternatives Considered
- **SQLite database:** Adds a dependency and schema migration concern; overkill for a portfolio project.
- **In-memory log:** Not durable; lost on process exit.
- **Structured log (Python `logging`):** Mixed with application logs; harder to parse programmatically.

### Consequences
- Audit trail is human-readable (one JSON object per line).
- Can be queried with standard tools (`jq`, etc.).
- Not suitable for high-throughput production use (file locking), but acceptable for this use case.

---

## ADR-005: Single LLM Provider (Anthropic)

**Status:** Accepted  
**Date:** 2026-08-28

### Context
Supporting multiple LLM providers adds abstraction complexity. The project demonstrates the agent architecture, not provider portability.

### Decision
Use Anthropic's `claude-sonnet-5` via the `anthropic` Python SDK. All LLM calls go through a single `LLMClient` wrapper that could be replaced with another provider's client in a future iteration.

### Consequences
- Simpler code; no provider abstraction layer.
- Requires an Anthropic API key to run.
- Tool-use (function calling) API is Anthropic-specific; migration to another provider would require adapting tool schemas.

---

## ADR-006: No Execution Engine — Decision Support Only

**Status:** Accepted  
**Date:** 2026-08-29

### Context
A treasury system that can initiate real payments, trades, or transfers introduces significant risk if the AI reasoning is incorrect. The project goal is a portfolio demonstration, not a production execution system.

### Decision
TreasuryAI has no execution engine. All consequential recommendations are returned with `status=PENDING_APPROVAL`. When a human approves via the CLI, the approval is logged and a description of the action is printed — nothing is sent to a real system.

### Consequences
- Zero risk of accidental financial transactions.
- The human-in-the-loop pattern is architecturally enforced (not just policy).
- Limits the "wow factor" of the demo, but correctly represents responsible AI system design.

---

## ADR-007: Synthetic Data Only

**Status:** Accepted  
**Date:** 2026-08-31

### Context
A portfolio project cannot use real client financial data. Even anonymised real data introduces privacy and legal risk.

### Decision
All financial data is generated by `data/synthetic_loader.py` from YAML scenario files. The data is realistic in structure and scale but entirely fabricated. No connection to any bank, broker, or market data provider.

### Consequences
- No data privacy or compliance concerns.
- Scenario files allow controlled demonstration of specific situations (stress, FX shock, etc.).
- Tools and agents are tested against consistent, reproducible data.

---

## ADR-008: Agents Do Not Communicate Directly

**Status:** Accepted  
**Date:** 2026-09-01

### Context
Allowing peer-to-peer agent communication creates a complex graph of possible interactions that is hard to reason about, test, and audit.

### Decision
All inter-agent communication is mediated by ORION. Specialist agents (ATLAS, CORA, TARA, FIRA) are isolated from each other. ARIA communicates only with ORION. This creates a star topology with ORION at the centre.

### Alternatives Considered
- **Mesh topology:** Any agent can call any other. More flexible but exponentially harder to audit.
- **Pipeline:** Fixed sequence (A → B → C). Too rigid for ad-hoc queries.

### Consequences
- ORION is a potential bottleneck but also a single point for routing logic and audit.
- Each specialist agent can be tested in complete isolation.
- Adding a new agent means adding one route in ORION — no changes to other specialists.

---

## ADR-009: System Prompts as Module Constants

**Status:** Accepted  
**Date:** 2026-09-02

### Context
System prompts define agent behaviour. They could be stored in config files, a database, or inline in code.

### Decision
Each agent's system prompt is a Python string constant at the top of the agent's module file (e.g. `ATLAS_SYSTEM_PROMPT = "..."` in `agents/atlas.py`). They are not user-configurable at runtime.

### Rationale
- Prompts are part of the agent's specification; changing them changes agent behaviour. This should require a code change and code review, not a config file edit.
- Co-location with agent code makes the agent's full specification readable in one file.
- Avoids the complexity of prompt versioning, templating engines, or a prompt management system.

### Consequences
- Changing a prompt requires a code change (intentional friction).
- Prompts are version-controlled in git alongside the code they govern.

---

## ADR-010: No Docker — Pure Python Local Run

**Status:** Accepted  
**Date:** 2026-09-02

### Context
Docker adds reproducibility but also complexity and a dependency that not all reviewers of a portfolio project will have.

### Decision
The project runs with `python -m venv` and `pip install`. No Docker, no docker-compose, no external services. The only external dependency at runtime is the Anthropic API.

### Consequences
- Lower barrier to try the project.
- Relies on Python 3.11+ being available (documented as a requirement).
- If the project were to grow to need a database or message broker, this decision would be revisited.

---

## ADR-011: `MockLLMClient` for All Agent Tests

**Status:** Accepted  
**Date:** 2026-09-03

### Context
Agent integration tests that call the real Anthropic API are slow, expensive, non-deterministic, and require a valid API key in CI.

### Decision
`core/llm_client.py` exports both `LLMClient` (real) and `MockLLMClient` (scripted). All tests in `tests/` use `MockLLMClient`. The mock is configured with fixture files in `tests/fixtures/` that define exactly what the LLM "says" in response to each message.

### Consequences
- Tests run in milliseconds, require no API key, and are fully deterministic.
- Test fixtures must be maintained when tool schemas change.
- Does not test prompt quality — that requires manual review or separate prompt evaluation.
