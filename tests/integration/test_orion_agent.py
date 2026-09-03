"""Integration tests for OrionAgent, using MockLLMClient throughout (ADR-011).

Each specialist gets its own MockLLMClient (scripted from the same fixtures
Phase 5 built), all sharing one AuditLogger/session_id so the whole run
lands in a single audit trail, plus a separate MockLLMClient for ORION's
own synthesis call.
"""

from pathlib import Path

import pytest

from decimal import Decimal

from agents.atlas import AtlasAgent
from agents.cora import CoraAgent
from agents.fira import FiraAgent
from agents.orion import OrionAgent
from agents.tara import TaraAgent
from core.audit import AuditLogger
from core.llm_client import MockLLMClient
from data.synthetic_loader import SyntheticDataLoader
from models.financial import AlertEvent, AlertSeverity, TriageRequest
from models.requests import AgentRequest
from models.responses import ResponseStatus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SESSION_ID = "sess-orion-1"


@pytest.fixture
def snapshot():
    return SyntheticDataLoader().load_scenario("base_case")


@pytest.fixture
def audit_logger(tmp_path):
    return AuditLogger(SESSION_ID, audit_dir=tmp_path)


def _specialist(cls, fixture_name, snapshot, audit_logger):
    llm = MockLLMClient.from_fixture(FIXTURES / fixture_name)
    return cls(llm_client=llm, snapshot=snapshot, audit_logger=audit_logger)


def _orion(specialists, audit_logger, synthesis_fixture="orion_synthesis.json") -> OrionAgent:
    orion_llm = MockLLMClient.from_fixture(FIXTURES / synthesis_fixture)
    return OrionAgent(llm_client=orion_llm, specialists=specialists, audit_logger=audit_logger)


def _request(query: str) -> AgentRequest:
    return AgentRequest(session_id=SESSION_ID, request_id="req-1", user_query=query)


def test_daily_briefing_invokes_atlas_cora_fira_and_completes(snapshot, audit_logger):
    specialists = {
        "ATLAS": _specialist(AtlasAgent, "atlas_happy_path.json", snapshot, audit_logger),
        "CORA": _specialist(CoraAgent, "cora_happy_path.json", snapshot, audit_logger),
        "FIRA": _specialist(FiraAgent, "fira_happy_path.json", snapshot, audit_logger),
    }
    orion = _orion(specialists, audit_logger)

    response = orion.run(_request("Give me the daily treasury briefing"))

    assert set(response.agents_invoked) == {"ATLAS", "CORA", "FIRA"}
    assert response.status == ResponseStatus.COMPLETE
    assert response.approval_required is False
    assert "ATLAS" in response.specialist_summaries
    assert response.final_briefing

    entries = audit_logger.read_session(SESSION_ID)
    response_entries = [e for e in entries if e.event_type.value == "AGENT_RESPONSE"]
    assert {e.agent_id for e in response_entries} == {"ATLAS", "CORA", "FIRA", "ORION"}


def test_liquidity_stress_invokes_atlas_and_tara_with_stress_results(snapshot, audit_logger):
    specialists = {
        "ATLAS": _specialist(AtlasAgent, "atlas_stress_low_severity.json", snapshot, audit_logger),
        "TARA": _specialist(TaraAgent, "tara_happy_path.json", snapshot, audit_logger),
    }
    orion = _orion(specialists, audit_logger)

    response = orion.run(_request("Run a liquidity stress test"))

    assert set(response.agents_invoked) == {"ATLAS", "TARA"}
    assert response.status == ResponseStatus.COMPLETE
    atlas_response = orion.last_specialist_responses["ATLAS"]
    assert atlas_response.stress_results is not None
    assert atlas_response.stress_results.severity.value == "LOW"


def test_approval_gate_propagates_from_specialist_to_orion(snapshot, audit_logger):
    specialists = {
        "ATLAS": _specialist(AtlasAgent, "atlas_approval_gate.json", snapshot, audit_logger),
        "TARA": _specialist(TaraAgent, "tara_happy_path.json", snapshot, audit_logger),
    }
    orion = _orion(specialists, audit_logger)

    response = orion.run(_request("Run a liquidity stress test"))

    assert response.status == ResponseStatus.PENDING_APPROVAL
    assert response.approval_required is True
    assert len(response.recommendations) == 1
    assert response.recommendations[0].requires_approval is True


def test_unknown_intent_routes_to_fira_only(snapshot, audit_logger):
    specialists = {
        "ATLAS": _specialist(AtlasAgent, "atlas_happy_path.json", snapshot, audit_logger),
        "FIRA": _specialist(FiraAgent, "fira_happy_path.json", snapshot, audit_logger),
    }
    orion = _orion(specialists, audit_logger)

    response = orion.run(_request("What's generally going on with the business?"))

    assert response.agents_invoked == ["FIRA"]
    assert response.status == ResponseStatus.COMPLETE


def test_no_specialists_wired_returns_error(snapshot, audit_logger):
    orion = _orion(specialists={}, audit_logger=audit_logger)

    response = orion.run(_request("Run a liquidity stress test"))

    assert response.status == ResponseStatus.ERROR
    assert response.agents_invoked == []
    assert "No specialist was available" in response.final_briefing


def test_specialist_error_propagates_to_orion_error_status(snapshot, audit_logger):
    specialists = {
        "ATLAS": _specialist(AtlasAgent, "atlas_error_path.json", snapshot, audit_logger),
        "TARA": _specialist(TaraAgent, "tara_happy_path.json", snapshot, audit_logger),
    }
    orion = _orion(specialists, audit_logger)

    response = orion.run(_request("Run a liquidity stress test"))

    assert response.status == ResponseStatus.ERROR
    assert response.approval_required is False


def test_triage_alert_routes_to_the_recommended_specialist(snapshot, audit_logger):
    specialists = {
        "ATLAS": _specialist(AtlasAgent, "atlas_happy_path.json", snapshot, audit_logger),
        "TARA": _specialist(TaraAgent, "tara_happy_path.json", snapshot, audit_logger),
    }
    orion = _orion(specialists, audit_logger)

    alert = AlertEvent(
        rule_id="LIQ-001", metric="lcr", threshold=Decimal("1.10"), actual_value=Decimal("1.074"),
        severity=AlertSeverity.CRITICAL, message="LCR below 110%", timestamp="2026-09-03T00:00:00Z",
    )
    triage_request = TriageRequest(alert=alert, recommended_agent="ATLAS", note="Escalate to ATLAS")

    response = orion.triage_alert(triage_request, _request("triage this alert"))

    assert response.agents_invoked == ["ATLAS"]
    assert response.status == ResponseStatus.COMPLETE


def test_triage_alert_with_unavailable_specialist_returns_error(snapshot, audit_logger):
    specialists = {"TARA": _specialist(TaraAgent, "tara_happy_path.json", snapshot, audit_logger)}
    orion = _orion(specialists, audit_logger)

    alert = AlertEvent(
        rule_id="LIQ-001", metric="lcr", threshold=Decimal("1.10"), actual_value=Decimal("1.074"),
        severity=AlertSeverity.CRITICAL, message="LCR below 110%", timestamp="2026-09-03T00:00:00Z",
    )
    triage_request = TriageRequest(alert=alert, recommended_agent="ATLAS", note="Escalate to ATLAS")

    response = orion.triage_alert(triage_request, _request("triage this alert"))

    assert response.status == ResponseStatus.ERROR
    assert response.agents_invoked == []
