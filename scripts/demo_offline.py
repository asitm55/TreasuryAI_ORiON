#!/usr/bin/env python
"""Run the TreasuryAI demo with NO ANTHROPIC_API_KEY and NO network calls.

Every LLM call is replaced with MockLLMClient, scripted with a small set of
realistic tool calls per agent (the same mechanism all 335 automated tests
use - ADR-011). This demonstrates the real architecture end-to-end: real
tool execution against tools/*.py, real Pydantic response models, real
audit logging, real approval-gate flow, real Rich rendering. The one thing
it does NOT show is live model reasoning/tool choice - that part is canned,
not generated. See scripts/demo.py for the same workflow against a real
model (requires ANTHROPIC_API_KEY).

    python scripts/demo_offline.py --scenario liquidity_stress
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow `python scripts/demo_offline.py` from anywhere

from rich.console import Console

import scripts.demo as demo
from core.llm_client import LLMResponse, MockLLMClient, ToolCallRequest

# Each agent's script is replayed as many times as it's invoked across the
# 5 demo steps (see scripts/demo.py:DEMO_STEPS); repeating covers any agent
# invoked more than once without running out of scripted turns.
_REPEATS = 4


def _script(*turns: LLMResponse) -> MockLLMClient:
    return MockLLMClient(list(turns) * _REPEATS)


def _atlas_client() -> MockLLMClient:
    return _script(
        LLMResponse(
            content="Checking current liquidity ratios against the snapshot.",
            stop_reason="tool_use",
            tool_calls=[
                ToolCallRequest(id="a1", name="calculate_lcr", input={"hqla": "52500000", "net_cash_outflows_30d": "37500000"}),
                ToolCallRequest(id="a2", name="calculate_nsfr", input={"available_stable_funding": "40000000", "required_stable_funding": "33700000"}),
            ],
        ),
        LLMResponse(content="LCR and NSFR are both comfortably above the 100% regulatory minimum.", stop_reason="end_turn"),
    )


def _cora_client() -> MockLLMClient:
    return _script(
        LLMResponse(
            content="Pulling the 30-day forecast and net cash position.",
            stop_reason="tool_use",
            tool_calls=[
                ToolCallRequest(id="c1", name="get_cash_flow_forecast", input={"horizon_days": 30}),
                ToolCallRequest(id="c2", name="calculate_net_cash_position", input={}),
            ],
        ),
        LLMResponse(content="Net cash position is healthy with a positive 30-day forecast.", stop_reason="end_turn"),
    )


def _tara_client() -> MockLLMClient:
    return _script(
        LLMResponse(
            content="Reviewing current FX exposure.",
            stop_reason="tool_use",
            tool_calls=[ToolCallRequest(id="t1", name="calculate_fx_exposure", input={})],
        ),
        LLMResponse(content="FX book looks reasonably hedged; no immediate action needed.", stop_reason="end_turn"),
    )


def _fira_client() -> MockLLMClient:
    return _script(
        LLMResponse(
            content="Scoring this period's KPIs.",
            stop_reason="tool_use",
            tool_calls=[
                ToolCallRequest(
                    id="f1", name="calculate_kpi_scores",
                    input={"metrics": {"dpo": "40.5", "dso": "48.7"}, "targets": {"dpo": "45", "dso": "45"}},
                )
            ],
        ),
        LLMResponse(content="Performance is broadly healthy this period, DPO trailing target slightly.", stop_reason="end_turn"),
    )


def _aria_client() -> MockLLMClient:
    return _script(
        LLMResponse(
            content="Evaluating alert rules against current metrics.",
            stop_reason="tool_use",
            tool_calls=[ToolCallRequest(id="ar1", name="evaluate_alert_rules", input={"metrics": {"lcr": "1.4", "nsfr": "1.187"}})],
        ),
        LLMResponse(content="No breaches this period.", stop_reason="end_turn"),
    )


def _orion_client() -> MockLLMClient:
    return _script(LLMResponse(content="Treasury position is healthy overall this period.", stop_reason="end_turn"))


_FACTORY = {
    "ATLAS": _atlas_client,
    "CORA": _cora_client,
    "TARA": _tara_client,
    "FIRA": _fira_client,
    "ARIA": _aria_client,
    "ORION": _orion_client,
}


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for the --scenario flag."""
    parser = argparse.ArgumentParser(prog="scripts/demo_offline.py", description="Run the demo with no API key (scripted LLM responses).")
    parser.add_argument("--scenario", default="base_case", help="Synthetic data scenario to load (default: base_case)")
    return parser


def main() -> None:
    """Script entry point: parse --scenario and run the demo with scripted LLM clients."""
    args = build_parser().parse_args()
    console = Console()
    console.print("[dim](offline mode: LLM responses are scripted, not live - no ANTHROPIC_API_KEY needed)[/dim]\n")
    demo.run_demo(args.scenario, console, llm_client_factory=lambda agent_id: _FACTORY[agent_id]())


if __name__ == "__main__":
    main()
