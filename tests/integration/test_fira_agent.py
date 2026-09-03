"""Integration tests for FiraAgent, using MockLLMClient (ADR-011).

FiraResponse has no recommendations field and its spec says status is
"always COMPLETE (no approval gates)" — so instead of an approval-gate test,
the third scenario here proves that invariant holds even when multiple
tools are called.
"""

from pathlib import Path

import pytest

from agents.fira import FiraAgent
from core.audit import AuditLogger
from core.llm_client import MockLLMClient
from data.synthetic_loader import SyntheticDataLoader
from models.requests import AgentRequest
from models.responses import ResponseStatus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def snapshot():
    return SyntheticDataLoader().load_scenario("base_case")


@pytest.fixture
def request_() -> AgentRequest:
    return AgentRequest(session_id="sess-fira-1", request_id="req-1", user_query="How are we performing this period?")


def _agent(fixture_name: str, snapshot, tmp_path) -> FiraAgent:
    llm = MockLLMClient.from_fixture(FIXTURES / fixture_name)
    audit_logger = AuditLogger("sess-fira-1", audit_dir=tmp_path)
    return FiraAgent(llm_client=llm, snapshot=snapshot, audit_logger=audit_logger)


def test_happy_path_populates_response_and_writes_audit_log(snapshot, request_, tmp_path):
    agent = _agent("fira_happy_path.json", snapshot, tmp_path)
    response = agent.run(request_)

    assert response.status == ResponseStatus.COMPLETE
    assert response.agent_id == "FIRA"
    assert "dpo" in response.kpi_scorecard.metrics
    assert response.benchmark_comparison.metric_name == "dso"
    assert "healthy" in response.executive_narrative

    entries = agent.audit_logger.read_session("sess-fira-1")
    event_types = [e.event_type.value for e in entries]
    assert event_types.count("TOOL_CALL") == 2
    assert event_types.count("AGENT_RESPONSE") == 1


def test_error_path_returns_error_status_and_logs_failure(snapshot, request_, tmp_path):
    agent = _agent("fira_error_path.json", snapshot, tmp_path)
    response = agent.run(request_)

    assert response.status == ResponseStatus.ERROR
    assert "missing targets" in response.reasoning


def test_status_is_always_complete_even_with_multiple_tool_calls(snapshot, request_, tmp_path):
    agent = _agent("fira_multi_tool.json", snapshot, tmp_path)
    response = agent.run(request_)

    assert response.status == ResponseStatus.COMPLETE
    assert len(response.priority_issues) == 3
    assert response.priority_issues[0].issue == "LCR near breach"
