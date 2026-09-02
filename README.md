# TreasuryAI

A multi-agent AI platform for finance and treasury decision support. It combines
deterministic Python financial tools with LLM-powered reasoning agents (ORION,
ATLAS, CORA, TARA, FIRA, ARIA) to produce auditable, human-reviewable
recommendations. All data is synthetic; there is no execution engine.

## Install

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configure

```bash
cp .env.example .env
# then set ANTHROPIC_API_KEY in .env
```

## Run

```bash
# Interactive CLI
python main.py

# Scripted end-to-end demo (once implemented, see Phase 7)
python scripts/demo.py --scenario liquidity_stress
```

## Test

```bash
pytest tests/ --cov
```

## Project status

Currently at **Phase 0 — Project Scaffolding**. The CLI runs but agent/tool logic
is not yet implemented.

## Layout

```
agents/   # ORION orchestrator + specialist agents (ATLAS, CORA, TARA, FIRA, ARIA)
tools/    # Deterministic Python financial calculation functions
models/   # Pydantic data models (financial, requests, responses, audit)
data/     # Synthetic data loader and scenario files
core/     # Shared infrastructure (config, LLM client, audit log, tool registry)
tests/    # Unit and integration tests
```
