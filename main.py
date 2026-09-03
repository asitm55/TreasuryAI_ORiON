"""TreasuryAI CLI entry point.

Run `python main.py` with no subcommand for the interactive REPL, or
`python main.py <command>` for a single one-shot invocation. Every command
goes through a TreasurySession, which wires the five specialists + ORION
together behind one shared AuditLogger and TreasurySnapshot.

TreasurySession's llm_client_factory is the dependency-injection point that
lets tests (and scripts/demo.py) substitute MockLLMClient per agent instead
of the real anthropic-backed LLMClient — see ADR-011.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from agents.aria import AriaAgent
from agents.atlas import AtlasAgent
from agents.cora import CoraAgent
from agents.fira import FiraAgent
from agents.orion import OrionAgent
from agents.tara import TaraAgent
from core.audit import AuditLogger
from core.config import get_settings
from core.llm_client import LLMClient
from data.synthetic_loader import SyntheticDataLoader
from models.audit import ApprovalGate, AuditEntry, EventType
from models.requests import AgentRequest
from models.responses import AgentResponse, AriaResponse, OrionResponse, ResponseStatus

__version__ = "0.1.0"
BANNER = f"TreasuryAI v{__version__} - Finance & Treasury Agent Platform"

AGENT_STYLES: dict[str, str] = {
    "ATLAS": "cyan", "CORA": "green", "TARA": "magenta", "FIRA": "yellow", "ARIA": "red", "ORION": "bold blue",
}
STATUS_STYLES: dict[str, str] = {"COMPLETE": "green", "PENDING_APPROVAL": "yellow", "ERROR": "red"}
SEVERITY_STYLES: dict[str, str] = {"CRITICAL": "bold red", "HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan", "INFO": "white"}


class TreasurySession:
    """One scenario's specialists + ORION, wired to a shared audit log."""

    def __init__(
        self,
        scenario: str = "base_case",
        llm_client_factory: Callable[[str], Any] | None = None,
        audit_dir: str | None = None,
    ):
        settings = get_settings()
        self.session_id = str(uuid.uuid4())
        self.snapshot = SyntheticDataLoader().load_scenario(scenario)
        self.audit_logger = AuditLogger(self.session_id, audit_dir=audit_dir or settings.audit_dir)

        factory = llm_client_factory or (lambda agent_id: LLMClient())

        self.atlas = AtlasAgent(llm_client=factory("ATLAS"), snapshot=self.snapshot, audit_logger=self.audit_logger)
        self.cora = CoraAgent(llm_client=factory("CORA"), snapshot=self.snapshot, audit_logger=self.audit_logger)
        self.tara = TaraAgent(llm_client=factory("TARA"), snapshot=self.snapshot, audit_logger=self.audit_logger)
        self.fira = FiraAgent(llm_client=factory("FIRA"), snapshot=self.snapshot, audit_logger=self.audit_logger)
        self.aria = AriaAgent(llm_client=factory("ARIA"), snapshot=self.snapshot, audit_logger=self.audit_logger)
        self.orion = OrionAgent(
            llm_client=factory("ORION"),
            specialists={"ATLAS": self.atlas, "CORA": self.cora, "TARA": self.tara, "FIRA": self.fira},
            audit_logger=self.audit_logger,
        )

    def make_request(self, user_query: str) -> AgentRequest:
        """Build a fresh AgentRequest scoped to this session and its scenario."""
        return AgentRequest(
            session_id=self.session_id,
            request_id=str(uuid.uuid4()),
            user_query=user_query,
            scenario=self.snapshot.scenario_name,
        )


# --- rendering ---------------------------------------------------------------


def _render_orion_response(console: Console, response: OrionResponse) -> None:
    for agent_id, summary in response.specialist_summaries.items():
        style = AGENT_STYLES.get(agent_id, "white")
        console.print(f"[{style}][{agent_id}][/{style}] {summary}")
    console.print()
    console.print(
        Panel(response.final_briefing, title="[bold blue]ORION - Briefing[/bold blue]", border_style=STATUS_STYLES[response.status.value])
    )
    if response.status == ResponseStatus.PENDING_APPROVAL:
        console.print("[yellow][!] PENDING APPROVAL[/yellow]")
    elif response.status == ResponseStatus.ERROR:
        console.print(f"[red][x] {response.reasoning}[/red]")


def _render_aria_response(console: Console, response: AriaResponse) -> None:
    if not response.alerts:
        console.print("[green]No alert rules breached.[/green]")
        return

    table = Table(title="Alerts")
    table.add_column("Rule")
    table.add_column("Metric")
    table.add_column("Severity")
    table.add_column("Message")
    for alert in response.alerts:
        style = SEVERITY_STYLES[alert.severity.value]
        table.add_row(alert.rule_id, alert.metric, f"[{style}]{alert.severity.value}[/{style}]", alert.message)
    console.print(table)

    for triage in response.triage_requests:
        console.print(f"  -> recommend triage with [bold]{triage.recommended_agent}[/bold]: {triage.note}")


def _prompt_approval(session: TreasurySession, console: Console, response: AgentResponse, auto_decline: bool = False) -> None:
    """Displays each PENDING_APPROVAL recommendation and asks the operator
    to approve or reject it. Per ADR-006, approval is logged and a
    description printed — nothing is ever actually executed.
    """
    if response.status != ResponseStatus.PENDING_APPROVAL:
        return

    for rec in getattr(response, "recommendations", None) or []:
        console.print(
            Panel(
                f"{rec.action}\n\n[dim]{rec.rationale}[/dim]\n\nEstimated impact: {rec.estimated_impact}",
                title="[bold yellow]PENDING APPROVAL[/bold yellow]",
                border_style="yellow",
            )
        )
        if auto_decline:
            approved = False
            console.print("[dim](auto-declined - non-interactive demo run)[/dim]")
        else:
            approved = Confirm.ask("Approve?")

        session.audit_logger.log(
            AuditEntry(
                timestamp=_utcnow(),
                session_id=session.session_id,
                agent_id="OPERATOR",
                event_type=EventType.APPROVAL_GATE,
                payload=ApprovalGate(
                    recommendation_id=str(uuid.uuid4()), approved=approved, timestamp=_utcnow()
                ).model_dump(mode="json"),
            )
        )
        if approved:
            console.print("[green]Approved.[/green] Action description logged - nothing is executed (decision-support only, ADR-006).")
        else:
            console.print("[red]Rejected.[/red] No action taken.")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- commands ------------------------------------------------------------------


def cmd_brief(session: TreasurySession, console: Console) -> OrionResponse:
    """Daily Treasury Briefing workflow: ORION routes to ATLAS, CORA, and FIRA."""
    console.print("[bold blue][ORION][/bold blue] Generating daily treasury briefing...")
    response = session.orion.run(session.make_request("Give me the daily treasury briefing"))
    _render_orion_response(console, response)
    return response


def cmd_stress_test(session: TreasurySession, console: Console) -> OrionResponse:
    """Liquidity Stress Test workflow: ORION routes to ATLAS and TARA."""
    console.print("[bold blue][ORION][/bold blue] Running a liquidity stress test...")
    response = session.orion.run(session.make_request("Run a liquidity stress test"))
    _render_orion_response(console, response)
    return response


def cmd_risk_review(session: TreasurySession, console: Console) -> OrionResponse:
    """FX Risk Review workflow: ORION routes to TARA and FIRA."""
    console.print("[bold blue][ORION][/bold blue] Running an FX and treasury risk review...")
    response = session.orion.run(session.make_request("Run an FX and treasury risk review"))
    _render_orion_response(console, response)
    return response


def cmd_alerts(session: TreasurySession, console: Console) -> AriaResponse:
    """Evaluate alert rules by calling ARIA directly (ORION must not invoke ARIA)."""
    console.print("[red][ARIA][/red] Evaluating alert rules against current metrics...")
    response = session.aria.run(session.make_request("Evaluate all alert rules against current metrics"))
    _render_aria_response(console, response)
    return response


def cmd_ask(session: TreasurySession, console: Console, question: str | None) -> OrionResponse | None:
    """Ad-hoc Query workflow: ORION classifies intent and routes to the relevant specialist(s)."""
    if not question:
        console.print("[red]Usage: ask <question>[/red]")
        return None
    console.print("[bold blue][ORION][/bold blue] Routing your question...")
    response = session.orion.run(session.make_request(question))
    _render_orion_response(console, response)
    return response


_COMMANDS: dict[str, Callable[[TreasurySession, Console, str | None], AgentResponse | None]] = {
    "brief": lambda session, console, _arg: cmd_brief(session, console),
    "stress-test": lambda session, console, _arg: cmd_stress_test(session, console),
    "risk-review": lambda session, console, _arg: cmd_risk_review(session, console),
    "alerts": lambda session, console, _arg: cmd_alerts(session, console),
    "ask": lambda session, console, arg: cmd_ask(session, console, arg),
}


def dispatch_command(session: TreasurySession, console: Console, command: str, argument: str | None, auto_decline_approval: bool = False) -> AgentResponse | None:
    """Run one command against session and prompt for approval if it's pending."""
    if command not in _COMMANDS:
        raise KeyError(command)
    response = _COMMANDS[command](session, console, argument)
    if response is not None:
        _prompt_approval(session, console, response, auto_decline=auto_decline_approval)
    return response


# --- CLI wiring ----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for both one-shot commands and the --scenario flag."""
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


def run_interactive(scenario: str, console: Console) -> None:
    """REPL: read a command per line, dispatch it, repeat until quit/exit/EOF."""
    session = TreasurySession(scenario=scenario)
    console.print(f"Scenario: [bold]{scenario}[/bold] | Session: {session.session_id}")
    console.print("Commands: brief, stress-test, risk-review, alerts, ask <question>, quit\n")

    while True:
        try:
            raw = console.input("[bold]TreasuryAI >[/bold] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\nExiting.")
            break

        raw = raw.strip()
        if not raw:
            continue
        command, _, rest = raw.partition(" ")
        if command in ("quit", "exit"):
            console.print("Goodbye.")
            break

        try:
            dispatch_command(session, console, command, rest or None)
        except KeyError:
            console.print(f"[red]Unknown command:[/red] '{command}'. Try: brief, stress-test, risk-review, alerts, ask <question>, quit")
        console.print()

    console.print(f"Audit log: {session.audit_logger.log_path}")


def run_one_shot(args: argparse.Namespace, console: Console) -> None:
    """Build a session and run exactly one command, then exit."""
    if args.command == "quit":
        return
    session = TreasurySession(scenario=args.scenario)
    question = " ".join(args.question) if args.command == "ask" else None
    dispatch_command(session, console, args.command, question)
    console.print(f"\nAudit log: {session.audit_logger.log_path}")


def main() -> None:
    """CLI entry point: parse args, then run interactively or one-shot."""
    parser = build_parser()
    args = parser.parse_args()

    console = Console()
    console.print(BANNER, style="bold")

    try:
        if args.command is None:
            run_interactive(args.scenario, console)
        else:
            run_one_shot(args, console)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
