#!/usr/bin/env python
"""Scripted end-to-end demo: runs all five TreasuryAI workflows in sequence
against one scenario, using the real Anthropic-backed LLMClient by default.

    python scripts/demo.py --scenario liquidity_stress

Requires ANTHROPIC_API_KEY (see .env.example) unless llm_client_factory is
overridden programmatically — run_demo() accepts the same dependency-
injection point as main.TreasurySession, which tests use to substitute
MockLLMClient (see tests/integration/test_demo_script.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow `python scripts/demo.py` from anywhere

from rich.console import Console
from rich.rule import Rule

import main as cli
from main import TreasurySession

DEMO_QUESTION = "How does our working capital position compare to peers?"

DEMO_STEPS: list[tuple[str, str, str | None]] = [
    ("Daily Treasury Briefing", "brief", None),
    ("Liquidity Stress Test", "stress-test", None),
    ("FX / Treasury Risk Review", "risk-review", None),
    ("Alert Evaluation", "alerts", None),
    (f"Ad-hoc Question: {DEMO_QUESTION}", "ask", DEMO_QUESTION),
]


def run_demo(scenario: str, console: Console, llm_client_factory: Callable[[str], Any] | None = None) -> TreasurySession:
    session = TreasurySession(scenario=scenario, llm_client_factory=llm_client_factory)
    console.print(cli.BANNER, style="bold")
    console.print(f"Scenario: [bold]{scenario}[/bold] | Session: {session.session_id}\n")

    for title, command, argument in DEMO_STEPS:
        console.print(Rule(title))
        cli.dispatch_command(session, console, command, argument, auto_decline_approval=True)
        console.print()

    console.print(Rule("Demo complete"))
    console.print(f"Audit log: {session.audit_logger.log_path}")
    return session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scripts/demo.py", description="Run every TreasuryAI workflow against one scenario.")
    parser.add_argument("--scenario", default="base_case", help="Synthetic data scenario to load (default: base_case)")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    console = Console()
    try:
        run_demo(args.scenario, console)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
