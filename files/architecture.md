# TreasuryAI — System Architecture

## 1. Overview

TreasuryAI is a multi-agent AI platform for finance and treasury decision support. It combines deterministic Python financial tools with LLM-powered reasoning agents to produce auditable, human-reviewable recommendations. No real banking credentials are used; all data is synthetic.

```
┌─────────────────────────────────────────────────────────────────┐
│                        User / Operator                          │
│                  (CLI · Web Dashboard · API)                     │
└────────────────────────────┬────────────────────────────────────┘
                             │  natural-language request
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ORION  (Orchestrator)                         │
│   • Parses intent          • Routes to specialist agents         │
│   • Aggregates results     • Enforces approval gates             │
│   • Writes audit log       • Returns final response              │
└──────┬──────────┬───────────────┬──────────────┬────────────────┘
       │          │               │              │
       ▼          ▼               ▼              ▼
  ┌─────────┐ ┌─────────┐ ┌─────────────┐ ┌──────────┐
  │  ATLAS  │ │  CORA   │ │    TARA     │ │   FIRA   │
  │Treasury │ │  Cash   │ │   Risk      │ │Financial │
  │Liquidity│ │   Ops   │ │ Assessment  │ │Intelligence│
  └────┬────┘ └────┬────┘ └──────┬──────┘ └────┬─────┘
       │           │             │              │
       └───────────┴─────────────┴──────────────┘
                             │
                    ┌────────▼────────┐
                    │  Python Tools   │
                    │  (Deterministic │
                    │   Calculations) │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   ARIA          │
                    │  Monitoring &   │
                    │  Alerting       │
                    └─────────────────┘
```

---

## 2. Core Architectural Principles

| # | Principle | Implementation |
|---|-----------|----------------|
| 1 | **LLMs never calculate** | All arithmetic/financial logic lives in Python `tools/` functions |
| 2 | **Deterministic tools** | Tools are pure functions with typed inputs/outputs and unit tests |
| 3 | **Agents reason, not compute** | Agents select tools, interpret results, and write explanations |
| 4 | **Structured outputs** | Every agent response is a Pydantic model (serialisable to JSON) |
| 5 | **Full auditability** | Every tool call and agent decision is appended to an audit log |
| 6 | **No live credentials** | Synthetic data loader replaces any real bank/market connection |
| 7 | **Human-in-the-loop** | Consequential actions return `status=PENDING_APPROVAL`; nothing executes without explicit human sign-off |
| 8 | **Simple over clever** | Flat file layout, minimal dependencies, standard Python stdlib where possible |

---

## 3. Repository Layout

```
treasuryai/
│
├── agents/                    # One module per agent
│   ├── __init__.py
│   ├── orion.py               # Orchestrator
│   ├── atlas.py               # Treasury & Liquidity
│   ├── cora.py                # Cash Operations
│   ├── tara.py                # Treasury Risk
│   ├── fira.py                # Financial Intelligence
│   └── aria.py                # Monitoring & Alerts
│
├── tools/                     # Deterministic Python tools (no LLM)
│   ├── __init__.py
│   ├── liquidity.py           # Liquidity ratios, coverage, LCR
│   ├── cash_flow.py           # Forecasting, variance, position
│   ├── risk.py                # VaR, duration, FX exposure
│   ├── analytics.py           # Trend, benchmarking, KPI scoring
│   └── alerts.py              # Threshold checks, rule engine
│
├── models/                    # Pydantic data models
│   ├── __init__.py
│   ├── financial.py           # Core financial data types
│   ├── requests.py            # Agent input models
│   ├── responses.py           # Agent output models
│   └── audit.py               # Audit log entry models
│
├── data/                      # Synthetic data
│   ├── synthetic_loader.py    # Generates/loads synthetic data
│   ├── scenarios/             # Named scenario YAML files
│   │   ├── base_case.yaml
│   │   ├── liquidity_stress.yaml
│   │   └── fx_shock.yaml
│   └── fixtures/              # Static JSON fixtures for tests
│
├── core/                      # Shared infrastructure
│   ├── __init__.py
│   ├── audit.py               # AuditLogger — append-only JSONL
│   ├── llm_client.py          # Thin Anthropic API wrapper
│   ├── tool_registry.py       # Maps tool names → functions
│   └── config.py              # Settings (env vars, defaults)
│
├── tests/                     # Test suite
│   ├── unit/                  # tools/ and models/ unit tests
│   ├── integration/           # agent workflow tests
│   └── fixtures/              # shared test data
│
├── docs/                      # Design documents
│   ├── architecture.md        ← this file
│   ├── agent-specifications.md
│   ├── implementation-plan.md
│   └── decisions.md
│
├── scripts/
│   └── demo.py                # End-to-end demo runner
│
├── main.py                    # CLI entry point
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 4. Agent Layer

Each agent is a Python class that:
1. Accepts a typed Pydantic request model.
2. Calls the Anthropic API with a fixed system prompt and a tool list.
3. Receives tool-use requests from the LLM; dispatches them to `tools/`.
4. Iterates until the LLM emits a final text response.
5. Wraps output in a Pydantic response model.
6. Logs every tool call and response to the audit log.

```python
# Canonical agent interaction loop (pseudocode)
class BaseAgent:
    def run(self, request: AgentRequest) -> AgentResponse:
        messages = self._build_messages(request)
        while True:
            llm_response = llm_client.complete(messages, tools=self.tools)
            if llm_response.stop_reason == "tool_use":
                tool_results = self._dispatch_tools(llm_response.tool_calls)
                messages = append_tool_results(messages, tool_results)
                audit_logger.log(tool_calls, tool_results)
            else:
                return self._build_response(llm_response.text)
```

---

## 5. Tool Layer

Tools are **pure Python functions**. They:
- Accept and return Pydantic models or primitives.
- Perform no I/O, no LLM calls, no side effects.
- Raise `ToolError` (a typed exception) on invalid input.
- Are registered in `core/tool_registry.py` and exposed to agents as Anthropic tool schemas.

```python
# Example signature
def calculate_lcr(
    hqla: Decimal,
    net_cash_outflows_30d: Decimal,
) -> LCRResult:
    """Liquidity Coverage Ratio per Basel III."""
    if net_cash_outflows_30d <= 0:
        raise ToolError("net_cash_outflows_30d must be positive")
    ratio = hqla / net_cash_outflows_30d
    return LCRResult(ratio=ratio, compliant=ratio >= Decimal("1.0"))
```

---

## 6. Data Model Layer

All inter-component data is typed. The three key model families:

| Family | Module | Purpose |
|--------|--------|---------|
| **Financial** | `models/financial.py` | `CashPosition`, `FXExposure`, `LiquidityMetrics`, `RiskMetrics`, … |
| **Request/Response** | `models/requests.py`, `models/responses.py` | `AgentRequest`, `AgentResponse`, `Recommendation`, `AlertEvent` |
| **Audit** | `models/audit.py` | `AuditEntry`, `ToolCall`, `ApprovalGate` |

All monetary values use Python `Decimal` (not `float`) to prevent rounding errors.

---

## 7. Audit & Governance Layer

`core/audit.py` exposes an `AuditLogger` that writes append-only JSONL to `audit/run_<timestamp>.jsonl`. Every entry contains:

- `timestamp` (ISO-8601 UTC)
- `agent_id`
- `session_id`
- `event_type`: `TOOL_CALL | TOOL_RESULT | AGENT_RESPONSE | APPROVAL_GATE | ALERT`
- `payload` (the full structured data)

The audit file is never modified after writing. No consequential action may bypass an `APPROVAL_GATE` entry.

---

## 8. Approval Gate Pattern

```
ORION assembles recommendation
        │
        ▼
AgentResponse(status=PENDING_APPROVAL, recommendation=…)
        │
        ▼
Operator reviews & types "approve" / "reject"
        │
        ├─ approve → AuditLogger.log(APPROVAL_GATE, approved=True)
        │            → action description printed; nothing actually executed
        │
        └─ reject  → AuditLogger.log(APPROVAL_GATE, approved=False)
                     → session ends with no action
```

The platform is **decision-support only**. There is no execution engine; approvals are logged and printed, never sent to a real system.

---

## 9. LLM Integration

- Provider: Anthropic (`claude-sonnet-5`)
- All agents share a single thin `LLMClient` wrapper in `core/llm_client.py`.
- Tool schemas are generated automatically from Python function signatures using a `@tool` decorator and `tool_registry.py`.
- System prompts are stored as constants in each agent module (not in config files) to keep agent behaviour explicit and reviewable.
- `max_tokens` per agent call is capped per agent (see agent specs).

---

## 10. Configuration

`core/config.py` reads from environment variables with sane defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Required |
| `TREASURYAI_MODEL` | `claude-sonnet-5` | LLM model |
| `TREASURYAI_SCENARIO` | `base_case` | Synthetic data scenario |
| `TREASURYAI_AUDIT_DIR` | `./audit` | Audit log directory |
| `TREASURYAI_LOG_LEVEL` | `INFO` | Log verbosity |

---

## 11. Local Execution

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Set API key
export ANTHROPIC_API_KEY=sk-...

# Run interactive CLI
python main.py

# Run end-to-end demo
python scripts/demo.py --scenario liquidity_stress

# Run tests
pytest tests/
```

---

## 12. Key Quality Attributes

| Attribute | Approach |
|-----------|----------|
| **Correctness** | Financial tools have 100% unit test coverage; outputs validated by Pydantic |
| **Transparency** | All tool calls visible in audit log; LLM reasoning captured in response |
| **Safety** | No live credentials; approval gates on all consequential outputs |
| **Maintainability** | Each agent is a single file; tools are stateless pure functions |
| **Testability** | Agents are tested with a mock LLM client; tools tested independently |
| **Portability** | Pure Python; no Docker required; runs on any OS with Python 3.11+ |
