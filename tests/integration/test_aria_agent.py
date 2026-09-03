"""Integration tests for AriaAgent, using MockLLMClient (ADR-011).

AriaResponse has no recommendations field and status is always COMPLETE
(agent-specifications.md), so the third scenario here proves the
check_threshold -> classify_alert_severity chaining (breach injection)
works correctly instead of an approval-gate test.
"""

from pathlib import Path

import pytest

from agents.aria import AriaAgent
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
    return AgentRequest(session_id="sess-aria-1", request_id="req-1", user_query="Any alerts right now?")


def _agent(fixture_name: str, snapshot, tmp_path) -> AriaAgent:
    llm = MockLLMClient.from_fixture(FIXTURES / fixture_name)
    audit_logger = AuditLogger("sess-aria-1", audit_dir=tmp_path)
    return AriaAgent(llm_client=llm, snapshot=snapshot, audit_logger=audit_logger)


def test_happy_path_populates_response_and_writes_audit_log(snapshot, request_, tmp_path):
    agent = _agent("aria_happy_path.json", snapshot, tmp_path)
    response = agent.run(request_)

    assert response.status == ResponseStatus.COMPLETE
    assert response.agent_id == "ARIA"
    assert {a.rule_id for a in response.alerts} == {"LIQ-001", "LIQ-002"}
    assert response.critical_count == 1
    assert response.high_count == 1
    assert {t.recommended_agent for t in response.triage_requests} == {"ATLAS"}

    entries = agent.audit_logger.read_session("sess-aria-1")
    event_types = [e.event_type.value for e in entries]
    assert event_types.count("TOOL_CALL") == 1
    assert event_types.count("AGENT_RESPONSE") == 1


def test_error_path_returns_error_status_and_logs_failure(snapshot, request_, tmp_path):
    agent = _agent("aria_error_path.json", snapshot, tmp_path)
    response = agent.run(request_)

    assert response.status == ResponseStatus.ERROR
    assert "metrics must not be empty" in response.reasoning


def test_classify_alert_severity_chains_from_prior_check_threshold(snapshot, request_, tmp_path):
    agent = _agent("aria_chained_threshold.json", snapshot, tmp_path)
    response = agent.run(request_)

    assert response.status == ResponseStatus.COMPLETE
    entries = agent.audit_logger.read_session("sess-aria-1")
    tool_results = [e for e in entries if e.event_type.value == "TOOL_RESULT"]
    assert len(tool_results) == 2
    # classify_alert_severity's injected `breach` was the check_threshold
    # result: value=12M > threshold=10M is a 20% breach -> MEDIUM.
    assert tool_results[1].payload["output"] == "MEDIUM"
