"""Agent input models."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from models.base import TreasuryBaseModel


class AgentRequest(TreasuryBaseModel):
    """A single request to any agent: the query, its session, and which scenario to use."""

    session_id: str
    request_id: str
    user_query: str
    context: dict[str, Any] = Field(default_factory=dict)
    scenario: str = "base_case"
