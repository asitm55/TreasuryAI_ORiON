"""Agent input models."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from models.base import TreasuryBaseModel


class AgentRequest(TreasuryBaseModel):
    session_id: str
    request_id: str
    user_query: str
    context: dict[str, Any] = Field(default_factory=dict)
    scenario: str = "base_case"
