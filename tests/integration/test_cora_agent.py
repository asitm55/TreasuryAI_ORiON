"""Integration tests for CoraAgent, using MockLLMClient (ADR-011)."""

from pathlib import Path

import pytest

from agents.cora import CoraAgent
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
    return AgentRequest(session_id="sess-cora-1", request_id="req-1", user_query="What's our cash position?")


def _agent(fixture_name: str, snapshot, tmp_path) -> CoraAgent:
    llm = MockLLMClient.from_fixture(FIXTURES / fixture_name)
    audit_logger = AuditLogger("sess-cora-1", audit_dir=tmp_path)
    return CoraAgent(llm_client=llm, snapshot=snapshot, audit_logger=audit_logger)


def test_happy_path_populates_response_and_writes_audit_log(snapshot, request_, tmp_path):
    agent = _agent("cora_happy_path.json", snapshot, tmp_path)
    response = agent.run(request_)

    assert response.status == ResponseStatus.COMPLETE
    assert response.agent_id == "CORA"
    assert response.net_cash_position.amount > 0
    assert response.working_capital.dso > 0
    assert len(response.forecast_30d.periods) > 0
    assert response.recommendations == []

    entries = agent.audit_logger.read_session("sess-cora-1")
    event_types = [e.event_type.value for e in entries]
    assert event_types.count("TOOL_CALL") == 3
    assert event_types.count("TOOL_RESULT") == 3
    assert event_types.count("AGENT_RESPONSE") == 1


def test_error_path_returns_error_status_and_logs_failure(snapshot, request_, tmp_path):
    agent = _agent("cora_error_path.json", snapshot, tmp_path)
    response = agent.run(request_)

    assert response.status == ResponseStatus.ERROR
    assert "at least 2 points" in response.reasoning

    entries = agent.audit_logger.read_session("sess-cora-1")
    tool_result_entries = [e for e in entries if e.event_type.value == "TOOL_RESULT"]
    assert len(tool_result_entries) == 1
    assert tool_result_entries[0].payload["error"] is not None


def test_approval_gate_sets_pending_approval_status(snapshot, request_, tmp_path):
    agent = _agent("cora_approval_gate.json", snapshot, tmp_path)
    response = agent.run(request_)

    assert response.status == ResponseStatus.PENDING_APPROVAL
    assert len(response.recommendations) == 1
    assert response.recommendations[0].requires_approval is True
    assert len(response.sweep_opportunities) > 0
