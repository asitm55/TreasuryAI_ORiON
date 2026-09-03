"""Tests for core/llm_client.py. No live API calls — ADR-011.

LLMClient (the real Anthropic wrapper) is tested by monkeypatching
anthropic.Anthropic with a fake that returns a scripted Message-shaped
object, so its parsing logic is covered without any network access.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.llm_client import LLMClient, LLMResponse, MockLLMClient, ToolCallRequest

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "sample_llm_responses.json"


def test_mock_llm_client_returns_scripted_responses_in_order():
    responses = [
        LLMResponse(content="", stop_reason="tool_use", tool_calls=[ToolCallRequest(id="1", name="calculate_lcr", input={"hqla": "100"})]),
        LLMResponse(content="LCR looks healthy.", stop_reason="end_turn"),
    ]
    mock = MockLLMClient(responses)

    first = mock.complete(messages=[{"role": "user", "content": "brief"}])
    assert first.stop_reason == "tool_use"
    assert first.tool_calls[0].name == "calculate_lcr"
    assert first.tool_calls[0].input == {"hqla": "100"}

    second = mock.complete(messages=[{"role": "user", "content": "brief"}])
    assert second.stop_reason == "end_turn"
    assert second.content == "LCR looks healthy."


def test_mock_llm_client_records_received_calls():
    mock = MockLLMClient([LLMResponse(content="ok", stop_reason="end_turn")])
    mock.complete(messages=[{"role": "user", "content": "hi"}], system="be terse", max_tokens=256)

    assert len(mock.received_calls) == 1
    call = mock.received_calls[0]
    assert call["system"] == "be terse"
    assert call["max_tokens"] == 256
    assert call["messages"] == [{"role": "user", "content": "hi"}]


def test_mock_llm_client_raises_when_scripted_responses_exhausted():
    mock = MockLLMClient([LLMResponse(content="only one", stop_reason="end_turn")])
    mock.complete(messages=[])
    with pytest.raises(IndexError):
        mock.complete(messages=[])


def test_mock_llm_client_from_fixture_parses_tool_use_and_end_turn():
    mock = MockLLMClient.from_fixture(FIXTURE_PATH)

    first = mock.complete(messages=[{"role": "user", "content": "brief"}])
    assert first.stop_reason == "tool_use"
    assert len(first.tool_calls) == 1
    assert first.tool_calls[0].name == "calculate_lcr"
    assert first.tool_calls[0].input["hqla"] == "52500000"
    assert first.usage["input_tokens"] == 512

    second = mock.complete(messages=[{"role": "user", "content": "brief"}])
    assert second.stop_reason == "end_turn"
    assert "140.0%" in second.content
    assert second.tool_calls == []


def test_mock_llm_client_from_fixture_accepts_string_path():
    mock = MockLLMClient.from_fixture(str(FIXTURE_PATH))
    assert mock.complete(messages=[]).stop_reason == "tool_use"


# --- LLMClient (real client, network mocked) --------------------------------


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.received_kwargs = None

    def create(self, **kwargs):
        self.received_kwargs = kwargs
        return self._response


class _FakeAnthropic:
    def __init__(self, response):
        self.messages = _FakeMessages(response)

    def __call__(self, api_key=None):
        return self


def _fake_message(content_blocks, stop_reason="end_turn", input_tokens=100, output_tokens=50):
    return SimpleNamespace(content=content_blocks, stop_reason=stop_reason, usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens))


def test_llm_client_parses_text_only_response(monkeypatch):
    fake_message = _fake_message([SimpleNamespace(type="text", text="LCR is healthy.")])
    fake_anthropic = _FakeAnthropic(fake_message)
    monkeypatch.setattr("core.llm_client.anthropic.Anthropic", lambda api_key=None: fake_anthropic)

    client = LLMClient(api_key="sk-test", model="claude-sonnet-5")
    result = client.complete(messages=[{"role": "user", "content": "brief"}])

    assert result.content == "LCR is healthy."
    assert result.stop_reason == "end_turn"
    assert result.tool_calls == []
    assert result.usage == {"input_tokens": 100, "output_tokens": 50}


def test_llm_client_parses_tool_use_response(monkeypatch):
    fake_message = _fake_message(
        [SimpleNamespace(type="tool_use", id="toolu_1", name="calculate_lcr", input={"hqla": "100"})],
        stop_reason="tool_use",
    )
    fake_anthropic = _FakeAnthropic(fake_message)
    monkeypatch.setattr("core.llm_client.anthropic.Anthropic", lambda api_key=None: fake_anthropic)

    client = LLMClient(api_key="sk-test")
    result = client.complete(messages=[{"role": "user", "content": "brief"}], tools=[{"name": "calculate_lcr"}])

    assert result.stop_reason == "tool_use"
    assert result.tool_calls == [ToolCallRequest(id="toolu_1", name="calculate_lcr", input={"hqla": "100"})]
    assert fake_anthropic.messages.received_kwargs["tools"] == [{"name": "calculate_lcr"}]


def test_llm_client_passes_system_and_max_tokens(monkeypatch):
    fake_message = _fake_message([SimpleNamespace(type="text", text="ok")])
    fake_anthropic = _FakeAnthropic(fake_message)
    monkeypatch.setattr("core.llm_client.anthropic.Anthropic", lambda api_key=None: fake_anthropic)

    client = LLMClient(api_key="sk-test")
    client.complete(messages=[{"role": "user", "content": "hi"}], system="be terse", max_tokens=256)

    kwargs = fake_anthropic.messages.received_kwargs
    assert kwargs["system"] == "be terse"
    assert kwargs["max_tokens"] == 256


def test_llm_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from core.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            LLMClient()
    finally:
        get_settings.cache_clear()
