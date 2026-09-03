"""Integration test for scripts/demo_offline.py — the no-API-key demo path."""

import io
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console

import scripts.demo_offline as demo_offline


@pytest.fixture
def console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False)


def test_main_runs_full_demo_with_no_api_key(monkeypatch, console):
    monkeypatch.setattr(demo_offline, "Console", lambda: console)
    monkeypatch.setattr(sys, "argv", ["demo_offline.py"])
    demo_offline.main()  # must not raise, must not touch ANTHROPIC_API_KEY

    output = console.file.getvalue()
    assert "offline mode" in output
    assert "Demo complete" in output
    assert "Audit log:" in output


def test_build_parser_accepts_scenario_override():
    parser = demo_offline.build_parser()
    args = parser.parse_args(["--scenario", "fx_shock"])
    assert args.scenario == "fx_shock"


def test_python_scripts_demo_offline_py_runs_with_no_env_key():
    """Runs the real entry point via subprocess with ANTHROPIC_API_KEY
    explicitly unset, proving this path truly needs no credentials.
    """
    import os

    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    result = subprocess.run(
        [sys.executable, "scripts/demo_offline.py"],
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert result.returncode == 0
    assert "Demo complete" in result.stdout
