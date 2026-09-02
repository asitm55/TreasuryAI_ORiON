"""Audit log entry models. See ADR-004: append-only JSONL audit trail."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from models.base import TreasuryBaseModel


class EventType(str, Enum):
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    AGENT_RESPONSE = "AGENT_RESPONSE"
    APPROVAL_GATE = "APPROVAL_GATE"
    ALERT = "ALERT"


class AuditEntry(TreasuryBaseModel):
    timestamp: datetime
    session_id: str
    agent_id: str
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolCall(TreasuryBaseModel):
    tool_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    call_id: str


class ToolResult(TreasuryBaseModel):
    call_id: str
    output: Any = None
    duration_ms: float = Field(ge=0)
    error: str | None = None


class ApprovalGate(TreasuryBaseModel):
    recommendation_id: str
    approved: bool
    approver_note: str | None = None
    timestamp: datetime
