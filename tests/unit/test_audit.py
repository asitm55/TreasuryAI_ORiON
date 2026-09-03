"""Tests for core/audit.py."""

import inspect
import json
from datetime import datetime, timezone

import pytest

from core.audit import AuditLogger
from models.audit import AuditEntry, EventType


def _entry(session_id: str = "sess-1", event_type: EventType = EventType.TOOL_CALL, payload: dict | None = None) -> AuditEntry:
    return AuditEntry(
        timestamp=datetime.now(timezone.utc),
        session_id=session_id,
        agent_id="ATLAS",
        event_type=event_type,
        payload=payload or {"tool": "calculate_lcr"},
    )


def test_log_creates_jsonl_file(tmp_path):
    logger = AuditLogger("sess-1", audit_dir=tmp_path)
    logger.log(_entry())

    assert logger.log_path.exists()
    assert logger.log_path.suffix == ".jsonl"
    assert logger.log_path.name.startswith("run_")
    assert logger.log_path.name.endswith("sess-1.jsonl")


def test_log_writes_parseable_jsonl_lines(tmp_path):
    logger = AuditLogger("sess-1", audit_dir=tmp_path)
    logger.log(_entry(payload={"tool": "calculate_lcr"}))
    logger.log(_entry(event_type=EventType.TOOL_RESULT, payload={"ratio": "1.4"}))

    lines = logger.log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["event_type"] == "TOOL_CALL"
    assert parsed[1]["event_type"] == "TOOL_RESULT"


def test_read_session_returns_logged_entries_in_order(tmp_path):
    logger = AuditLogger("sess-1", audit_dir=tmp_path)
    logger.log(_entry(payload={"step": 1}))
    logger.log(_entry(payload={"step": 2}))

    entries = logger.read_session("sess-1")
    assert len(entries) == 2
    assert entries[0].payload["step"] == 1
    assert entries[1].payload["step"] == 2
    assert all(isinstance(e, AuditEntry) for e in entries)


def test_read_session_for_unknown_session_returns_empty(tmp_path):
    logger = AuditLogger("sess-1", audit_dir=tmp_path)
    logger.log(_entry())
    assert logger.read_session("some-other-session") == []


def test_log_rejects_entry_for_a_different_session(tmp_path):
    logger = AuditLogger("sess-1", audit_dir=tmp_path)
    with pytest.raises(ValueError, match="does not match"):
        logger.log(_entry(session_id="sess-2"))


def test_read_session_skips_blank_lines(tmp_path):
    logger = AuditLogger("sess-1", audit_dir=tmp_path)
    logger.log(_entry(payload={"step": 1}))
    with logger.log_path.open("a", encoding="utf-8") as f:
        f.write("\n")
    logger.log(_entry(payload={"step": 2}))

    entries = logger.read_session("sess-1")
    assert len(entries) == 2


def test_audit_dir_created_if_missing(tmp_path):
    nested = tmp_path / "nested" / "audit"
    logger = AuditLogger("sess-1", audit_dir=nested)
    logger.log(_entry())
    assert nested.exists()


def test_public_api_has_no_delete_or_update_method():
    public_methods = {name for name, _ in inspect.getmembers(AuditLogger, predicate=inspect.isfunction) if not name.startswith("_")}
    assert public_methods == {"log", "read_session"}


def test_two_loggers_in_same_session_both_readable_via_read_session(tmp_path):
    first = AuditLogger("sess-1", audit_dir=tmp_path)
    first.log(_entry(payload={"run": "first"}))

    second = AuditLogger("sess-1", audit_dir=tmp_path)
    second.log(_entry(payload={"run": "second"}))

    entries = second.read_session("sess-1")
    payloads = {e.payload["run"] for e in entries}
    assert payloads == {"first", "second"}
