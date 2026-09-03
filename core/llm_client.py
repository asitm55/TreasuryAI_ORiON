"""Thin Anthropic API wrapper. See ADR-005 (single LLM provider) and
ADR-011 (MockLLMClient for all agent tests — no live API calls in tests).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import anthropic

from core.config import get_settings


@dataclass(frozen=True)
class ToolCallRequest:
    """One tool call the model asked to make: its id, tool name, and input."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    """Normalised result of one LLM completion, real or mocked."""

    content: str
    stop_reason: str
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


class LLMClientProtocol(Protocol):
    """Structural type both LLMClient and MockLLMClient satisfy."""

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse: ...


class LLMClient:
    """Real Anthropic API client. Never used in tests — see MockLLMClient."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self._client = anthropic.Anthropic(api_key=api_key or settings.require_api_key())
        self.model = model or settings.model

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Call the real Anthropic API and normalise its response into an LLMResponse."""
        kwargs: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        if system:
            kwargs["system"] = system

        message = self._client.messages.create(**kwargs)

        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCallRequest(id=block.id, name=block.name, input=dict(block.input)))

        usage = {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        }

        return LLMResponse(
            content="".join(text_parts),
            stop_reason=message.stop_reason or "end_turn",
            tool_calls=tool_calls,
            usage=usage,
        )


class MockLLMClient:
    """Scripted LLM client for tests (ADR-011). Returns pre-built LLMResponse
    objects in sequence, one per complete() call, regardless of input.
    """

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self._index = 0
        self.received_calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Return the next scripted LLMResponse, recording the call for inspection."""
        self.received_calls.append({"messages": messages, "tools": tools, "system": system, "max_tokens": max_tokens})
        if self._index >= len(self._responses):
            raise IndexError(
                f"MockLLMClient has no more scripted responses (received {len(self.received_calls)} calls, "
                f"only {len(self._responses)} scripted)"
            )
        response = self._responses[self._index]
        self._index += 1
        return response

    @classmethod
    def from_fixture(cls, fixture_path: str | Path) -> "MockLLMClient":
        """Build a MockLLMClient from a JSON fixture: a list of objects with
        content, stop_reason, tool_calls, and usage keys (see
        tests/fixtures/).
        """
        with Path(fixture_path).open("r", encoding="utf-8") as f:
            raw_responses = json.load(f)

        responses = [
            LLMResponse(
                content=raw.get("content", ""),
                stop_reason=raw["stop_reason"],
                tool_calls=[ToolCallRequest(**call) for call in raw.get("tool_calls", [])],
                usage=raw.get("usage", {}),
            )
            for raw in raw_responses
        ]
        return cls(responses)
