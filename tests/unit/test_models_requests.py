"""Instantiation and validation tests for models/requests.py."""

import pytest
from pydantic import ValidationError

from models.requests import AgentRequest


def test_agent_request_valid_with_defaults():
    req = AgentRequest(session_id="sess-1", request_id="req-1", user_query="What is our LCR today?")
    assert req.scenario == "base_case"
    assert req.context == {}


def test_agent_request_valid_with_explicit_context_and_scenario():
    req = AgentRequest(
        session_id="sess-1",
        request_id="req-1",
        user_query="Run a stress test",
        context={"entity": "HoldCo"},
        scenario="liquidity_stress",
    )
    assert req.context["entity"] == "HoldCo"
    assert req.scenario == "liquidity_stress"


def test_agent_request_rejects_missing_required_field():
    with pytest.raises(ValidationError):
        AgentRequest(session_id="sess-1", user_query="Missing request_id")
