"""Instantiation and validation tests for models/audit.py."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.audit import ApprovalGate, AuditEntry, EventType, ToolCall, ToolResult

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def test_audit_entry_valid():
    entry = AuditEntry(timestamp=NOW, session_id="sess-1", agent_id="ATLAS", event_type=EventType.TOOL_CALL, payload={"tool": "calculate_lcr"})
    assert entry.event_type == EventType.TOOL_CALL


def test_audit_entry_defaults_empty_payload():
    entry = AuditEntry(timestamp=NOW, session_id="sess-1", agent_id="ATLAS", event_type=EventType.ALERT)
    assert entry.payload == {}


def test_audit_entry_rejects_invalid_event_type():
    with pytest.raises(ValidationError):
        AuditEntry(timestamp=NOW, session_id="sess-1", agent_id="ATLAS", event_type="NOT_A_TYPE")


def test_tool_call_valid():
    ToolCall(tool_name="calculate_lcr", inputs={"hqla": "50000000", "net_cash_outflows_30d": "35000000"}, call_id="call-1")


def test_tool_result_valid():
    result = ToolResult(call_id="call-1", output={"ratio": "1.42", "compliant": True}, duration_ms=12.5)
    assert result.error is None


def test_tool_result_rejects_negative_duration():
    with pytest.raises(ValidationError):
        ToolResult(call_id="call-1", output=None, duration_ms=-1)


def test_approval_gate_valid():
    gate = ApprovalGate(recommendation_id="rec-1", approved=True, approver_note="Approved by treasurer", timestamp=NOW)
    assert gate.approved is True


def test_approval_gate_defaults_no_note():
    gate = ApprovalGate(recommendation_id="rec-1", approved=False, timestamp=NOW)
    assert gate.approver_note is None
