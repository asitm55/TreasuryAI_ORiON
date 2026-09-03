"""Tests for core/config.py."""

import pytest

from core.config import Settings, get_settings


def test_from_env_uses_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TREASURYAI_MODEL", raising=False)
    monkeypatch.delenv("TREASURYAI_SCENARIO", raising=False)
    monkeypatch.delenv("TREASURYAI_AUDIT_DIR", raising=False)
    monkeypatch.delenv("TREASURYAI_LOG_LEVEL", raising=False)

    settings = Settings.from_env()
    assert settings.anthropic_api_key is None
    assert settings.model == "claude-sonnet-5"
    assert settings.scenario == "base_case"
    assert settings.audit_dir == "./audit"
    assert settings.log_level == "INFO"


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("TREASURYAI_MODEL", "claude-opus-5")
    monkeypatch.setenv("TREASURYAI_SCENARIO", "fx_shock")

    settings = Settings.from_env()
    assert settings.anthropic_api_key == "sk-test"
    assert settings.model == "claude-opus-5"
    assert settings.scenario == "fx_shock"


def test_require_api_key_returns_key_when_set():
    settings = Settings(anthropic_api_key="sk-test", model="m", scenario="s", audit_dir="a", log_level="INFO")
    assert settings.require_api_key() == "sk-test"


def test_require_api_key_raises_when_missing():
    settings = Settings(anthropic_api_key=None, model="m", scenario="s", audit_dir="a", log_level="INFO")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        settings.require_api_key()


def test_get_settings_is_cached():
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    assert first is second
    get_settings.cache_clear()
