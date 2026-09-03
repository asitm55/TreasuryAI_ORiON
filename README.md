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
# Interactive CLI (or `python main.py <command>` for a one-shot run)
python main.py

# Scripted end-to-end demo: all 5 workflows in sequence
python scripts/demo.py --scenario liquidity_stress
```

Commands: `brief`, `stress-test`, `risk-review`, `alerts`, `ask <question>`, `quit`.

## Test

```bash
pytest tests/ --cov
```

## Project status

Phases 0-7 complete (scaffolding, data models, synthetic data layer, all 32
financial tools + tool registry, LLM client + audit logger, all five
specialist agents, the ORION orchestrator, and the CLI + demo script). Only
final polish/documentation (Phase 8) remains — see [phases/](phases/) for a
per-phase writeup of what was built and why, and `pytest tests/ --cov` for
current test coverage (335 tests, 99% project-wide — the only gap is two
`if __name__ == "__main__":` guards exercised by subprocess tests but not
tracked by in-process coverage).

## Layout

```
agents/   # ORION orchestrator + specialist agents (ATLAS, CORA, TARA, FIRA, ARIA)
tools/    # Deterministic Python financial calculation functions
models/   # Pydantic data models (financial, requests, responses, audit)
data/     # Synthetic data loader and scenario files
core/     # Shared infrastructure (config, LLM client, audit log, tool registry)
tests/    # Unit and integration tests
```
