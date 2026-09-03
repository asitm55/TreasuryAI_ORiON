"""Integration tests for main.py's CLI plumbing.

MockLLMClient instances are stateful (a finite queue of scripted
responses), and TreasurySession builds one per agent up front — so these
tests each dispatch exactly one command per session, matching how the
Phase 5/6 fixtures were scripted (2-3 turns each). scripts/demo.py's own
test uses a different, repeat-friendly mock since it dispatches 5 commands
against the same session.
"""

import io
import sys
from pathlib import Path

import pytest
from rich.console import Console

import main
from core.llm_client import LLMResponse, MockLLMClient
from models.responses import ResponseStatus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _factory(fixture_map: dict[str, str], default: str = "fira_happy_path.json"):
    """TreasurySession builds all 6 agents eagerly regardless of which
    command a test actually dispatches, so unlisted agent_ids fall back to
    a harmless default fixture (they're never invoked, just constructed).
    """
    def factory(agent_id: str):
        return MockLLMClient.from_fixture(FIXTURES / fixture_map.get(agent_id, default))
    return factory


@pytest.fixture
def console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False)


# --- TreasurySession wiring ---------------------------------------------------


def test_treasury_session_wires_all_agents(tmp_path):
    factory = _factory({})
    session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)

    assert session.snapshot.scenario_name == "base_case"
    assert set(session.orion.specialists.keys()) == {"ATLAS", "CORA", "TARA", "FIRA"}
    request = session.make_request("test question")
    assert request.session_id == session.session_id
    assert request.scenario == "base_case"


def test_treasury_session_loads_requested_scenario(tmp_path):
    factory = _factory({})
    session = main.TreasurySession(scenario="fx_shock", llm_client_factory=factory, audit_dir=tmp_path)
    assert session.snapshot.scenario_name == "fx_shock"


# --- dispatch_command ----------------------------------------------------------


def test_dispatch_command_brief(tmp_path, console):
    factory = _factory({"ATLAS": "atlas_happy_path.json", "CORA": "cora_happy_path.json", "FIRA": "fira_happy_path.json", "ORION": "orion_synthesis.json"})
    session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    response = main.dispatch_command(session, console, "brief", None)
    assert response.status == ResponseStatus.COMPLETE
    assert set(response.agents_invoked) == {"ATLAS", "CORA", "FIRA"}


def test_dispatch_command_risk_review(tmp_path, console):
    factory = _factory({"TARA": "tara_happy_path.json", "FIRA": "fira_happy_path.json", "ORION": "orion_synthesis.json"})
    session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    response = main.dispatch_command(session, console, "risk-review", None)
    assert set(response.agents_invoked) == {"TARA", "FIRA"}


def test_dispatch_command_alerts(tmp_path, console):
    factory = _factory({"ARIA": "aria_happy_path.json"})
    session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    response = main.dispatch_command(session, console, "alerts", None)
    assert len(response.alerts) == 2


def test_dispatch_command_ask_with_question(tmp_path, console):
    factory = _factory({"FIRA": "fira_happy_path.json", "ORION": "orion_synthesis.json"})
    session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    response = main.dispatch_command(session, console, "ask", "How are our KPIs trending?")
    assert response.agents_invoked == ["FIRA"]


def test_dispatch_command_ask_without_question_returns_none(tmp_path, console):
    factory = _factory({})
    session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    assert main.dispatch_command(session, console, "ask", None) is None


def test_dispatch_command_unknown_command_raises(tmp_path, console):
    factory = _factory({})
    session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    with pytest.raises(KeyError):
        main.dispatch_command(session, console, "not-a-command", None)


# --- approval gate ---------------------------------------------------------------


def test_approval_gate_auto_decline_logs_rejection(tmp_path, console):
    factory = _factory({"ATLAS": "atlas_approval_gate.json", "TARA": "tara_happy_path.json", "ORION": "orion_synthesis.json"})
    session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    response = main.dispatch_command(session, console, "stress-test", None, auto_decline_approval=True)

    assert response.status == ResponseStatus.PENDING_APPROVAL
    entries = session.audit_logger.read_session(session.session_id)
    gate_entries = [e for e in entries if e.event_type.value == "APPROVAL_GATE"]
    assert len(gate_entries) == 1
    assert gate_entries[0].payload["approved"] is False


def test_approval_gate_interactive_approval_logs_approval(tmp_path, console, monkeypatch):
    monkeypatch.setattr(main.Confirm, "ask", staticmethod(lambda *args, **kwargs: True))
    factory = _factory({"ATLAS": "atlas_approval_gate.json", "TARA": "tara_happy_path.json", "ORION": "orion_synthesis.json"})
    session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    main.dispatch_command(session, console, "stress-test", None, auto_decline_approval=False)

    entries = session.audit_logger.read_session(session.session_id)
    gate_entries = [e for e in entries if e.event_type.value == "APPROVAL_GATE"]
    assert len(gate_entries) == 1
    assert gate_entries[0].payload["approved"] is True


def test_prompt_approval_is_noop_for_complete_status(tmp_path, console):
    factory = _factory({"ATLAS": "atlas_happy_path.json", "CORA": "cora_happy_path.json", "FIRA": "fira_happy_path.json", "ORION": "orion_synthesis.json"})
    session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    response = main.dispatch_command(session, console, "brief", None)
    assert response.status == ResponseStatus.COMPLETE
    entries = session.audit_logger.read_session(session.session_id)
    assert not [e for e in entries if e.event_type.value == "APPROVAL_GATE"]


# --- rendering doesn't crash -----------------------------------------------------


def test_render_aria_response_with_no_alerts_does_not_crash(tmp_path, console):
    llm = MockLLMClient([LLMResponse(content="No breaches this period.", stop_reason="end_turn")])
    factory = _factory({})
    session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    session.aria.llm_client = llm  # override with a script that calls no tools -> no alerts
    response = main.dispatch_command(session, console, "alerts", None)
    assert response.alerts == []


def test_render_orion_response_error_status_does_not_crash(tmp_path, console):
    factory = _factory({})
    session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    session.orion.specialists = {}  # simulate "no specialist available" -> ERROR
    response = main.dispatch_command(session, console, "brief", None)
    assert response.status == ResponseStatus.ERROR


# --- build_parser / run_one_shot -------------------------------------------------


def test_build_parser_defaults_scenario_to_base_case():
    parser = main.build_parser()
    args = parser.parse_args([])
    assert args.scenario == "base_case"
    assert args.command is None


def test_build_parser_ask_requires_a_question():
    parser = main.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["ask"])


def test_build_parser_ask_joins_multiple_words():
    parser = main.build_parser()
    args = parser.parse_args(["ask", "what", "is", "our", "LCR"])
    assert args.question == ["what", "is", "our", "LCR"]


def test_run_one_shot_quit_does_not_build_a_session(console, monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("TreasurySession should not be constructed for 'quit'")

    monkeypatch.setattr(main, "TreasurySession", _fail)
    args = main.build_parser().parse_args(["quit"])
    main.run_one_shot(args, console)  # must not raise


def test_run_one_shot_dispatches_command_and_prints_audit_log(tmp_path, console, monkeypatch):
    factory = _factory({"ATLAS": "atlas_happy_path.json", "CORA": "cora_happy_path.json", "FIRA": "fira_happy_path.json", "ORION": "orion_synthesis.json"})
    real_session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    monkeypatch.setattr(main, "TreasurySession", lambda scenario: real_session)

    args = main.build_parser().parse_args(["brief"])
    main.run_one_shot(args, console)

    output = console.file.getvalue()
    assert "Audit log:" in output


def test_run_one_shot_ask_joins_question_words(tmp_path, console, monkeypatch):
    factory = _factory({"FIRA": "fira_happy_path.json", "ORION": "orion_synthesis.json"})
    real_session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    monkeypatch.setattr(main, "TreasurySession", lambda scenario: real_session)

    args = main.build_parser().parse_args(["ask", "how", "are", "our", "kpis"])
    main.run_one_shot(args, console)  # must not raise; question text isn't asserted since MockLLMClient ignores it


# --- run_interactive ----------------------------------------------------------


def test_run_interactive_processes_command_then_quits(tmp_path, monkeypatch):
    factory = _factory({"ATLAS": "atlas_happy_path.json", "CORA": "cora_happy_path.json", "FIRA": "fira_happy_path.json", "ORION": "orion_synthesis.json"})
    real_session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    monkeypatch.setattr(main, "TreasurySession", lambda scenario: real_session)

    console = Console(file=io.StringIO(), force_terminal=False)
    inputs = iter(["", "brief", "quit"])  # blank line is skipped
    monkeypatch.setattr(console, "input", lambda *a, **k: next(inputs))

    main.run_interactive("base_case", console)

    output = console.file.getvalue()
    assert "Goodbye." in output
    assert "Audit log:" in output


def test_run_interactive_reports_unknown_command(tmp_path, monkeypatch):
    factory = _factory({})
    real_session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    monkeypatch.setattr(main, "TreasurySession", lambda scenario: real_session)

    console = Console(file=io.StringIO(), force_terminal=False)
    inputs = iter(["bogus-command", "quit"])
    monkeypatch.setattr(console, "input", lambda *a, **k: next(inputs))

    main.run_interactive("base_case", console)

    assert "Unknown command" in console.file.getvalue()


def test_run_interactive_exits_cleanly_on_eof(tmp_path, monkeypatch):
    factory = _factory({})
    real_session = main.TreasurySession(scenario="base_case", llm_client_factory=factory, audit_dir=tmp_path)
    monkeypatch.setattr(main, "TreasurySession", lambda scenario: real_session)

    console = Console(file=io.StringIO(), force_terminal=False)

    def _raise_eof(*args, **kwargs):
        raise EOFError

    monkeypatch.setattr(console, "input", _raise_eof)
    main.run_interactive("base_case", console)

    assert "Exiting." in console.file.getvalue()


# --- main() ----------------------------------------------------------------------


def test_main_with_no_command_runs_interactive(monkeypatch):
    called = {}
    monkeypatch.setattr(main, "run_interactive", lambda scenario, console: called.setdefault("scenario", scenario))
    monkeypatch.setattr(sys, "argv", ["main.py"])
    main.main()
    assert called["scenario"] == "base_case"


def test_main_with_command_runs_one_shot(monkeypatch):
    called = {}
    monkeypatch.setattr(main, "run_one_shot", lambda args, console: called.setdefault("command", args.command))
    monkeypatch.setattr(sys, "argv", ["main.py", "brief"])
    main.main()
    assert called["command"] == "brief"


def test_main_exits_with_code_1_on_runtime_error(monkeypatch):
    def _raise(args, console):
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    monkeypatch.setattr(main, "run_one_shot", _raise)
    monkeypatch.setattr(sys, "argv", ["main.py", "brief"])
    with pytest.raises(SystemExit) as exc_info:
        main.main()
    assert exc_info.value.code == 1


def test_python_main_py_quit_runs_as_a_real_script():
    """Exercises the actual `if __name__ == "__main__":` entry point via
    subprocess — 'quit' needs no ANTHROPIC_API_KEY, so this is safe to run
    without live credentials while still proving the script itself works.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, "main.py", "quit"],
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "TreasuryAI" in result.stdout
