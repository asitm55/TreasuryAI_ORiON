"""Unit tests for agents/base.py mechanics, independent of any concrete agent."""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

import pytest

from agents.base import BaseAgent, ToolCallOutcome, to_jsonable
from core.audit import AuditLogger
from core.llm_client import LLMResponse, MockLLMClient, ToolCallRequest
from core.tool_registry import ToolError, ToolRegistry, tool
from data.synthetic_loader import SyntheticDataLoader
from models.requests import AgentRequest
from models.responses import AgentResponse, ResponseStatus


class _Direction(str, Enum):
    UP = "UP"


@pytest.fixture
def isolated_registry():
    registry = ToolRegistry()

    def add(a: Decimal, b: Decimal) -> Decimal:
        """Add two decimals."""
        return a + b

    def fail(message: str) -> None:
        """Always raises ToolError."""
        raise ToolError(message)

    registry.register(add, name="add")
    registry.register(fail, name="fail")
    return registry


class _EchoAgent(BaseAgent):
    agent_id = "ECHO"
    display_name = "Echo test agent"
    system_prompt = "test"
    tool_names = ("add", "fail")
    max_tokens = 256

    def _build_response(self, request, llm_response, reasoning, tool_results):
        return AgentResponse(agent_id=self.agent_id, request_id=request.request_id, status=ResponseStatus.COMPLETE, reasoning=reasoning)


@pytest.fixture
def snapshot():
    return SyntheticDataLoader().load_scenario("base_case")


@pytest.fixture
def request_():
    return AgentRequest(session_id="sess-echo", request_id="req-1", user_query="hi")


def _agent(responses, snapshot, tmp_path, registry) -> _EchoAgent:
    llm = MockLLMClient(responses)
    audit_logger = AuditLogger("sess-echo", audit_dir=tmp_path)
    return _EchoAgent(llm_client=llm, snapshot=snapshot, audit_logger=audit_logger, registry=registry)


# --- to_jsonable --------------------------------------------------------------


def test_to_jsonable_decimal():
    assert to_jsonable(Decimal("1.50")) == "1.50"


def test_to_jsonable_pydantic_model():
    from models.financial import LiquidityGap

    gap = LiquidityGap(tenor_bucket="0-7d", gap_amount=Decimal("-500000"), cumulative_gap=Decimal("-500000"))
    assert to_jsonable(gap) == {"tenor_bucket": "0-7d", "gap_amount": "-500000", "cumulative_gap": "-500000"}


def test_to_jsonable_enum():
    assert to_jsonable(_Direction.UP) == "UP"


def test_to_jsonable_dict():
    assert to_jsonable({"a": Decimal("1"), "b": _Direction.UP}) == {"a": "1", "b": "UP"}


def test_to_jsonable_nested_list_of_decimals():
    assert to_jsonable([Decimal("1"), Decimal("2")]) == ["1", "2"]


def test_to_jsonable_passthrough_for_plain_values():
    assert to_jsonable("plain") == "plain"
    assert to_jsonable(5) == 5
    assert to_jsonable(None) is None


# --- run() loop mechanics -------------------------------------------------------


def test_run_completes_without_any_tool_calls(snapshot, request_, tmp_path, isolated_registry):
    agent = _agent([LLMResponse(content="no tools needed", stop_reason="end_turn")], snapshot, tmp_path, isolated_registry)
    response = agent.run(request_)
    assert response.status == ResponseStatus.COMPLETE
    assert response.reasoning == "no tools needed"


def test_resolve_kwargs_applies_injection_resolver(snapshot, request_, tmp_path, isolated_registry):
    class _InjectingAgent(_EchoAgent):
        tool_injections = {"add": {"b": lambda agent, results: Decimal("100")}}

    responses = [
        LLMResponse(content="", stop_reason="tool_use", tool_calls=[ToolCallRequest(id="t1", name="add", input={"a": "1", "b": "999"})]),
        LLMResponse(content="done", stop_reason="end_turn"),
    ]
    llm = MockLLMClient(responses)
    audit_logger = AuditLogger("sess-echo", audit_dir=tmp_path)
    agent = _InjectingAgent(llm_client=llm, snapshot=snapshot, audit_logger=audit_logger, registry=isolated_registry)
    agent.run(request_)

    entries = agent.audit_logger.read_session("sess-echo")
    tool_result = next(e for e in entries if e.event_type.value == "TOOL_RESULT")
    assert tool_result.payload["output"] == "101"  # injected b=100 overrides the LLM's b=999


def test_run_dispatches_tool_call_and_continues(snapshot, request_, tmp_path, isolated_registry):
    responses = [
        LLMResponse(content="", stop_reason="tool_use", tool_calls=[ToolCallRequest(id="t1", name="add", input={"a": "1", "b": "2"})]),
        LLMResponse(content="done", stop_reason="end_turn"),
    ]
    agent = _agent(responses, snapshot, tmp_path, isolated_registry)
    response = agent.run(request_)
    assert response.status == ResponseStatus.COMPLETE

    entries = agent.audit_logger.read_session("sess-echo")
    assert [e.event_type.value for e in entries] == ["TOOL_CALL", "TOOL_RESULT", "AGENT_RESPONSE"]


def test_run_returns_error_response_and_logs_on_tool_error(snapshot, request_, tmp_path, isolated_registry):
    responses = [
        LLMResponse(content="", stop_reason="tool_use", tool_calls=[ToolCallRequest(id="t1", name="fail", input={"message": "boom"})]),
    ]
    agent = _agent(responses, snapshot, tmp_path, isolated_registry)
    response = agent.run(request_)
    assert response.status == ResponseStatus.ERROR
    assert "boom" in response.reasoning

    entries = agent.audit_logger.read_session("sess-echo")
    result_entry = next(e for e in entries if e.event_type.value == "TOOL_RESULT")
    assert result_entry.payload["error"] == "boom"


def test_run_returns_error_when_unknown_tool_is_called(snapshot, request_, tmp_path, isolated_registry):
    responses = [
        LLMResponse(content="", stop_reason="tool_use", tool_calls=[ToolCallRequest(id="t1", name="does_not_exist", input={})]),
    ]
    agent = _agent(responses, snapshot, tmp_path, isolated_registry)
    response = agent.run(request_)
    assert response.status == ResponseStatus.ERROR


def test_run_returns_error_when_max_iterations_exceeded(snapshot, request_, tmp_path, isolated_registry):
    # 8 MAX_TOOL_ITERATIONS worth of scripted tool_use responses that never end_turn.
    responses = [
        LLMResponse(content="", stop_reason="tool_use", tool_calls=[ToolCallRequest(id=f"t{i}", name="add", input={"a": "1", "b": "1"})])
        for i in range(10)
    ]
    agent = _agent(responses, snapshot, tmp_path, isolated_registry)
    response = agent.run(request_)
    assert response.status == ResponseStatus.ERROR
    assert "exceeded" in response.reasoning


# --- _all_flat -------------------------------------------------------------------


def test_all_flat_flattens_list_returning_tool_calls():
    tool_results = {"get_things": [[1, 2], [3]]}
    assert BaseAgent._all_flat(tool_results, "get_things") == [1, 2, 3]


def test_all_flat_empty_when_tool_never_called():
    assert BaseAgent._all_flat({}, "never_called") == []


# --- _last / _all ------------------------------------------------------------------


def test_last_returns_most_recent_call_result():
    tool_results = {"calc": [1, 2, 3]}
    assert BaseAgent._last(tool_results, "calc") == 3


def test_last_returns_none_when_never_called():
    assert BaseAgent._last({}, "calc") is None


def test_all_returns_every_call_result_in_order():
    tool_results = {"calc": [1, 2, 3]}
    assert BaseAgent._all(tool_results, "calc") == [1, 2, 3]
