"""Shared agent contract and agentic run() loop.

Design notes, since these aren't spelled out verbatim in the plan:

1. Tool-call parameter injection. Several tools take a TreasurySnapshot or a
   list of typed domain objects (list[InvestmentPosition], list[CashPosition])
   that core.tool_registry deliberately excludes from the LLM-facing schema
   (see that module's docstring) — those values always come from already-
   loaded data, never from the model. Each concrete agent declares a
   `tool_injections` map of {tool_name: {param_name: resolver}} so run()
   knows what to fill in before dispatching.

2. Structured recommendations via a tool call. Recommendation (action,
   rationale, estimated_impact, requires_approval) is narrative judgment,
   not a calculation — so no tools/*.py function produces one. Rather than
   parse it out of free text, agents that need recommendations (ATLAS, CORA,
   TARA) list `submit_recommendation` (defined below) as an available tool:
   the LLM emits a Recommendation the same way it reports any other
   structured result, through the existing tool-call/schema/dispatch
   machinery, keeping "structured output" a single mechanism rather than two.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Callable

from core.audit import AuditLogger
from core.llm_client import LLMResponse, ToolCallRequest
from core.tool_registry import ToolError, ToolNotFoundError, ToolRegistry, default_registry, tool
from data.synthetic_loader import TreasurySnapshot
from models.audit import AuditEntry, EventType
from models.audit import ToolCall as ToolCallEntry
from models.audit import ToolResult as ToolResultEntry
from models.requests import AgentRequest
from models.responses import AgentResponse, Recommendation, ResponseStatus

MAX_TOOL_ITERATIONS = 8


@tool
def submit_recommendation(action: str, rationale: str, estimated_impact: str, requires_approval: bool) -> Recommendation:
    """Emit one structured recommendation. Call this once per recommendation
    before finishing. Set requires_approval=true for any action that would
    move funds, adjust the portfolio, or otherwise have a real consequence.
    """
    return Recommendation(action=action, rationale=rationale, estimated_impact=estimated_impact, requires_approval=requires_approval)


def to_jsonable(value: Any) -> Any:
    """Best-effort conversion of a tool result (Pydantic models, Decimals,
    enums, nested lists/dicts) into plain JSON-serialisable Python values,
    for both the audit log and the tool_result message sent back to the LLM.
    """
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    return value


@dataclass
class ToolCallOutcome:
    call: ToolCallRequest
    result: Any = None
    error: str | None = None


class BaseAgent(ABC):
    agent_id: str
    display_name: str
    system_prompt: str
    tool_names: tuple[str, ...] = ()
    max_tokens: int = 1024
    # {tool_name: {param_name: resolver(agent, tool_results) -> value}}
    tool_injections: dict[str, dict[str, Callable[["BaseAgent", dict[str, list[Any]]], Any]]] = {}

    def __init__(
        self,
        llm_client: Any,
        snapshot: TreasurySnapshot,
        audit_logger: AuditLogger,
        registry: ToolRegistry = default_registry,
    ):
        self.llm_client = llm_client
        self.snapshot = snapshot
        self.audit_logger = audit_logger
        self.registry = registry

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [self.registry.get_tool_schema(name) for name in self.tool_names]

    def run(self, request: AgentRequest) -> AgentResponse:
        tool_results: dict[str, list[Any]] = {}
        context = self._build_context(request, tool_results)
        initial_content = f"{context}\n\n{request.user_query}" if context else request.user_query
        messages: list[dict[str, Any]] = [{"role": "user", "content": initial_content}]
        reasoning_parts: list[str] = []

        for _ in range(MAX_TOOL_ITERATIONS):
            llm_response = self.llm_client.complete(
                messages=messages, tools=self.tool_schemas(), system=self.system_prompt, max_tokens=self.max_tokens
            )
            if llm_response.content:
                reasoning_parts.append(llm_response.content)

            if llm_response.stop_reason != "tool_use":
                response = self._build_response(request, llm_response, "\n".join(reasoning_parts), tool_results)
                self._log(request, EventType.AGENT_RESPONSE, response.model_dump(mode="json"))
                return response

            outcomes = self._dispatch_all(request, llm_response.tool_calls, tool_results)
            failure = next((o for o in outcomes if o.error is not None), None)
            if failure is not None:
                return self._error_response(request, failure.error)

            messages.append({"role": "assistant", "content": self._assistant_tool_use_blocks(llm_response.tool_calls)})
            messages.append({"role": "user", "content": self._tool_result_blocks(outcomes)})

        return self._error_response(request, f"exceeded {MAX_TOOL_ITERATIONS} tool-use iterations without finishing")

    def _dispatch_all(
        self, request: AgentRequest, calls: list[ToolCallRequest], tool_results: dict[str, list[Any]]
    ) -> list[ToolCallOutcome]:
        outcomes: list[ToolCallOutcome] = []
        for call in calls:
            self._log(request, EventType.TOOL_CALL, ToolCallEntry(tool_name=call.name, inputs=call.input, call_id=call.id).model_dump(mode="json"))
            started = time.monotonic()
            try:
                kwargs = self._resolve_kwargs(call, tool_results)
                result = self.registry.dispatch(call.name, kwargs)
            except (ToolError, ToolNotFoundError, TypeError) as exc:
                duration_ms = (time.monotonic() - started) * 1000
                self._log(request, EventType.TOOL_RESULT, ToolResultEntry(call_id=call.id, output=None, duration_ms=duration_ms, error=str(exc)).model_dump(mode="json"))
                outcomes.append(ToolCallOutcome(call=call, error=str(exc)))
                continue

            duration_ms = (time.monotonic() - started) * 1000
            serialisable = to_jsonable(result)
            self._log(request, EventType.TOOL_RESULT, ToolResultEntry(call_id=call.id, output=serialisable, duration_ms=duration_ms, error=None).model_dump(mode="json"))
            tool_results.setdefault(call.name, []).append(result)
            outcomes.append(ToolCallOutcome(call=call, result=result))
        return outcomes

    def _resolve_kwargs(self, call: ToolCallRequest, tool_results: dict[str, list[Any]]) -> dict[str, Any]:
        kwargs = dict(call.input)
        for param_name, resolver in self.tool_injections.get(call.name, {}).items():
            kwargs[param_name] = resolver(self, tool_results)
        return kwargs

    @staticmethod
    def _assistant_tool_use_blocks(calls: list[ToolCallRequest]) -> list[dict[str, Any]]:
        return [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in calls]

    @staticmethod
    def _tool_result_blocks(outcomes: list[ToolCallOutcome]) -> list[dict[str, Any]]:
        return [{"type": "tool_result", "tool_use_id": o.call.id, "content": to_jsonable(o.result)} for o in outcomes]

    @staticmethod
    def _last(tool_results: dict[str, list[Any]], name: str) -> Any | None:
        calls = tool_results.get(name)
        return calls[-1] if calls else None

    @staticmethod
    def _all(tool_results: dict[str, list[Any]], name: str) -> list[Any]:
        return list(tool_results.get(name, []))

    @staticmethod
    def _all_flat(tool_results: dict[str, list[Any]], name: str) -> list[Any]:
        flat: list[Any] = []
        for call_result in tool_results.get(name, []):
            flat.extend(call_result)
        return flat

    def _log(self, request: AgentRequest, event_type: EventType, payload: dict[str, Any]) -> None:
        self.audit_logger.log(
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                session_id=request.session_id,
                agent_id=self.agent_id,
                event_type=event_type,
                payload=payload,
            )
        )

    def _build_context(self, request: AgentRequest, tool_results: dict[str, list[Any]]) -> str | None:
        """Optional text prepended to the first user message, ahead of
        request.user_query. A real LLM has no other way to learn the
        current snapshot's figures — MockLLMClient-driven tests don't need
        this (fixtures script the tool calls directly), but without it the
        CLI (Phase 7), talking to a real model, would have nothing to work
        from. Override to describe relevant data or to seed tool_results
        with real, audited tool calls the agent makes on its own before
        asking the LLM anything (see AriaAgent for an example of the
        latter — it dispatches calculate_lcr/calculate_nsfr itself via
        self._dispatch_all(), so those calls are logged exactly like any
        other, not silently computed outside the audit trail).
        """
        return None

    def _error_response(self, request: AgentRequest, error_message: str) -> AgentResponse:
        response = AgentResponse(
            agent_id=self.agent_id,
            request_id=request.request_id,
            status=ResponseStatus.ERROR,
            reasoning=f"Agent stopped due to a tool error: {error_message}",
        )
        self._log(request, EventType.AGENT_RESPONSE, response.model_dump(mode="json"))
        return response

    @abstractmethod
    def _build_response(
        self, request: AgentRequest, llm_response: LLMResponse, reasoning: str, tool_results: dict[str, list[Any]]
    ) -> AgentResponse:
        ...
