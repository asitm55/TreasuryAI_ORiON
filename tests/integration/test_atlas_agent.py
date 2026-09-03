"""Integration tests for AtlasAgent, using MockLLMClient (ADR-011)."""

from decimal import Decimal
from pathlib import Path

import pytest

from agents.atlas import AtlasAgent
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
    return AgentRequest(session_id="sess-atlas-1", request_id="req-1", user_query="What is our liquidity position?")


def _agent(fixture_name: str, snapshot, tmp_path) -> AtlasAgent:
    llm = MockLLMClient.from_fixture(FIXTURES / fixture_name)
    audit_logger = AuditLogger("sess-atlas-1", audit_dir=tmp_path)
    return AtlasAgent(llm_client=llm, snapshot=snapshot, audit_logger=audit_logger)


def test_happy_path_populates_response_and_writes_audit_log(snapshot, request_, tmp_path):
    agent = _agent("atlas_happy_path.json", snapshot, tmp_path)
    response = agent.run(request_)

    assert response.status == ResponseStatus.COMPLETE
    assert response.agent_id == "ATLAS"
    assert response.liquidity_metrics.lcr == Decimal("1.4")
    assert response.coverage_ratios.lcr_compliant is True
    assert response.recommendations == []
    assert "LCR" in response.reasoning

    entries = agent.audit_logger.read_session("sess-atlas-1")
    event_types = [e.event_type.value for e in entries]
    assert event_types.count("TOOL_CALL") == 2
    assert event_types.count("TOOL_RESULT") == 2
    assert event_types.count("AGENT_RESPONSE") == 1


def test_error_path_returns_error_status_and_logs_failure(snapshot, request_, tmp_path):
    agent = _agent("atlas_error_path.json", snapshot, tmp_path)
    response = agent.run(request_)

    assert response.status == ResponseStatus.ERROR
    assert "net_cash_outflows_30d" in response.reasoning

    entries = agent.audit_logger.read_session("sess-atlas-1")
    tool_result_entries = [e for e in entries if e.event_type.value == "TOOL_RESULT"]
    assert len(tool_result_entries) == 1
    assert tool_result_entries[0].payload["error"] is not None

    response_entries = [e for e in entries if e.event_type.value == "AGENT_RESPONSE"]
    assert len(response_entries) == 1
    assert response_entries[0].payload["status"] == "ERROR"


def test_approval_gate_sets_pending_approval_status(snapshot, request_, tmp_path):
    agent = _agent("atlas_approval_gate.json", snapshot, tmp_path)
    response = agent.run(request_)

    assert response.status == ResponseStatus.PENDING_APPROVAL
    assert len(response.recommendations) == 1
    assert response.recommendations[0].requires_approval is True
    assert response.stress_results is not None
    assert response.stress_results.severity.value == "HIGH"
