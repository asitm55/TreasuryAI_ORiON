"""Append-only JSONL audit trail. See ADR-004: no delete or update method
exists in the public API — audit entries are permanent once logged.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from models.audit import AuditEntry


class AuditLogger:
    """Append-only JSONL writer/reader for one session's audit trail."""

    def __init__(self, session_id: str, audit_dir: str | os.PathLike = "./audit"):
        self.session_id = session_id
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.log_path = self.audit_dir / f"run_{timestamp}_{session_id}.jsonl"
        self._lock = threading.Lock()

    def log(self, entry: AuditEntry) -> None:
        """Append entry to this session's log file, flushed and fsynced immediately."""
        if entry.session_id != self.session_id:
            raise ValueError(
                f"AuditEntry.session_id '{entry.session_id}' does not match "
                f"this logger's session_id '{self.session_id}'"
            )
        line = entry.model_dump_json() + "\n"
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

    def read_session(self, session_id: str) -> list[AuditEntry]:
        """Read every logged entry for session_id, across all run files
        (normally just this logger's own file, but glob handles the case of
        multiple runs sharing a session_id).
        """
        entries: list[AuditEntry] = []
        for path in sorted(self.audit_dir.glob(f"run_*_{session_id}.jsonl")):
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entries.append(AuditEntry(**json.loads(line)))
        return entries
