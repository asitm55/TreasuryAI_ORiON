# Phase 0 — Project Scaffolding

**Goal:** empty but fully wired skeleton that runs without errors.
**Status:** Complete

## What was built

- Package directories with `__init__.py`: `agents/`, `tools/`, `models/`, `core/`, `data/`.
- `core/config.py` — a `Settings` dataclass read from environment variables
  (`ANTHROPIC_API_KEY`, `TREASURYAI_MODEL`, `TREASURYAI_SCENARIO`,
  `TREASURYAI_AUDIT_DIR`, `TREASURYAI_LOG_LEVEL`), exposed via a cached
  `get_settings()` singleton. Reading settings never requires an API key —
  `require_api_key()` only raises when an agent actually needs to call the LLM.
- `main.py` — an argparse-based stub CLI with the `brief` / `stress-test` /
  `risk-review` / `alerts` / `ask` / `quit` subcommands wired as no-ops.
- `pyproject.toml`, `requirements.txt`, `.env.example`, `.gitignore`, `README.md`.
- `tests/{unit,integration,fixtures}`, `data/{scenarios,fixtures}`, `scripts/`,
  `audit/` scaffolded ahead of need since later phases write into them.

## Deviations / notes

- The banner originally used an em dash (`—`); swapped for a plain hyphen
  after it printed as `�` in a Windows console using a non-UTF-8 codepage.
- Planning docs (`architecture.md`, `agent-specifications.md`,
  `implementation-plan.md`, `decisions.md`) are kept locally under `docs/`
  and `files/` but are **not** tracked in git — the repo is scoped to
  implementation only (see `.gitignore`).

## Verify

```bash
python main.py --help
python main.py
```

Both run cleanly with no import errors.
