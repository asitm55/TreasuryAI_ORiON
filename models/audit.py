"""Audit log entry models. See ADR-004: append-only JSONL audit trail."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from models.base import TreasuryBaseModel


class EventType(str, Enum):
    """Kind of event recorded in the audit log."""

    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    AGENT_RESPONSE = "AGENT_RESPONSE"
    APPROVAL_GATE = "APPROVAL_GATE"
    ALERT = "ALERT"


class AuditEntry(TreasuryBaseModel):
    """One line of the append-only JSONL audit log (ADR-004)."""

    timestamp: datetime
    session_id: str
    agent_id: str
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolCall(TreasuryBaseModel):
    """Audit payload for a TOOL_CALL event: which tool, with what inputs."""

    tool_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    call_id: str


class ToolResult(TreasuryBaseModel):
    """Audit payload for a TOOL_RESULT event: outcome and timing of a prior ToolCall."""

    call_id: str
    output: Any = None
    duration_ms: float = Field(ge=0)
    error: str | None = None


class ApprovalGate(TreasuryBaseModel):
    """Audit payload for an operator's approve/reject decision on a Recommendation."""

    recommendation_id: str
    approved: bool
    approver_note: str | None = None
    timestamp: datetime
