"""TreasuryAI CLI entry point (stub — no agent logic yet, see Phase 7)."""

from __future__ import annotations

import argparse

__version__ = "0.1.0"

BANNER = f"TreasuryAI v{__version__} - Finance & Treasury Agent Platform"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=BANNER,
    )
    parser.add_argument(
        "--scenario",
        default="base_case",
        help="Synthetic data scenario to load (default: base_case)",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("brief", help="Generate the daily treasury briefing")
    subparsers.add_parser("stress-test", help="Run a liquidity stress test")
    subparsers.add_parser("risk-review", help="Run an FX / treasury risk review")
    subparsers.add_parser("alerts", help="Evaluate alert rules against current data")
    ask_parser = subparsers.add_parser("ask", help="Ask an ad-hoc treasury question")
    ask_parser.add_argument("question", nargs="+", help="The question to ask")
    subparsers.add_parser("quit", help="Exit the interactive session")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        print(BANNER)
        parser.print_usage()
        return

    print(BANNER)
    print(f"[stub] '{args.command}' is not yet implemented — see implementation-plan.md")


if __name__ == "__main__":
    main()
