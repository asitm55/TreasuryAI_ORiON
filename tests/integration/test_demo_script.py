"""Integration test for scripts/demo.py.

Unlike tests/integration/test_main_cli.py (which dispatches one command per
session, matching the exact per-command fixtures Phase 5/6 built),
run_demo() dispatches all 5 commands against the *same* session — several
agents (ATLAS, CORA, TARA, FIRA) get invoked more than once across the
5 steps. A finite scripted MockLLMClient from a Phase 5 fixture would run
out of responses partway through, so this test uses a simple client that
always answers immediately with text and calls no tools — sufficient to
prove the whole pipeline (rendering, dispatch, audit logging, the
approval-gate auto-decline path) runs cleanly end-to-end without crashing.
Specific per-tool outputs are already covered by Phase 5/6's tests.
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console

import scripts.demo as demo
from core.llm_client import LLMResponse, MockLLMClient


def _always_end_turn_factory(agent_id: str) -> MockLLMClient:
    # More than enough turns for any agent invoked multiple times across
    # the demo's 5 steps.
    return MockLLMClient([LLMResponse(content=f"{agent_id} has nothing further to add.", stop_reason="end_turn") for _ in range(20)])


@pytest.fixture
def console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False)


def test_run_demo_completes_all_five_steps(tmp_path, console):
    session = demo.run_demo("base_case", console, llm_client_factory=_always_end_turn_factory)

    output = console.file.getvalue()
    for title, _command, _arg in demo.DEMO_STEPS:
        assert title in output
    assert "Demo complete" in output
    assert "Audit log:" in output
    assert session.audit_logger.log_path.exists()


def test_run_demo_logs_entries_for_every_agent_touched(tmp_path, console):
    session = demo.run_demo("base_case", console, llm_client_factory=_always_end_turn_factory)

    entries = session.audit_logger.read_session(session.session_id)
    agent_ids = {e.agent_id for e in entries}
    # brief -> ATLAS/CORA/FIRA/ORION, stress-test -> ATLAS/TARA/ORION,
    # risk-review -> TARA/FIRA/ORION, alerts -> ARIA, ask (working capital) -> CORA/ORION.
    assert agent_ids == {"ATLAS", "CORA", "TARA", "FIRA", "ARIA", "ORION"}


def test_run_demo_uses_requested_scenario(tmp_path, console):
    session = demo.run_demo("liquidity_stress", console, llm_client_factory=_always_end_turn_factory)
    assert session.snapshot.scenario_name == "liquidity_stress"


def test_build_parser_defaults_to_base_case():
    parser = demo.build_parser()
    args = parser.parse_args([])
    assert args.scenario == "base_case"


def test_build_parser_accepts_scenario_override():
    parser = demo.build_parser()
    args = parser.parse_args(["--scenario", "fx_shock"])
    assert args.scenario == "fx_shock"


def test_main_exits_with_code_1_on_runtime_error(monkeypatch):
    def _raise(scenario, console):
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    monkeypatch.setattr(demo, "run_demo", _raise)
    monkeypatch.setattr(sys, "argv", ["demo.py"])
    with pytest.raises(SystemExit) as exc_info:
        demo.main()
    assert exc_info.value.code == 1


def test_main_calls_run_demo_with_parsed_scenario(monkeypatch):
    called = {}
    monkeypatch.setattr(demo, "run_demo", lambda scenario, console: called.setdefault("scenario", scenario))
    monkeypatch.setattr(sys, "argv", ["demo.py", "--scenario", "fx_shock"])
    demo.main()
    assert called["scenario"] == "fx_shock"


def test_python_scripts_demo_py_help_runs_as_a_real_script():
    """Exercises the actual `if __name__ == "__main__":` entry point via
    subprocess — --help needs no ANTHROPIC_API_KEY, so this is safe without
    live credentials while still proving the script itself runs.
    """
    result = subprocess.run(
        [sys.executable, "scripts/demo.py", "--help"],
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "scenario" in result.stdout
