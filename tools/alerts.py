"""Threshold checks and the alert rule engine. See agent-specifications.md's
"Alert Rules (initial set)" table for the rule catalogue this evaluates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Literal

from core.tool_registry import ToolError, tool
from models.audit import AuditEntry
from models.base import ExactDecimal, TreasuryBaseModel
from models.financial import AlertEvent, AlertSeverity


class ThresholdDirection(str, Enum):
    """Which side of a threshold counts as a breach."""

    ABOVE = "ABOVE"  # breach when value > threshold
    BELOW = "BELOW"  # breach when value < threshold


@dataclass(frozen=True)
class AlertRule:
    """One entry in the alert rule catalogue: a metric, its threshold, and severity."""

    rule_id: str
    metric: str
    threshold: Decimal
    direction: ThresholdDirection
    severity: AlertSeverity


# Matches agent-specifications.md's "Alert Rules (initial set)" table.
DEFAULT_ALERT_RULES: tuple[AlertRule, ...] = (
    AlertRule("LIQ-001", "lcr", Decimal("1.10"), ThresholdDirection.BELOW, AlertSeverity.CRITICAL),
    AlertRule("LIQ-002", "lcr", Decimal("1.30"), ThresholdDirection.BELOW, AlertSeverity.HIGH),
    AlertRule("LIQ-003", "nsfr", Decimal("1.05"), ThresholdDirection.BELOW, AlertSeverity.HIGH),
    AlertRule("CASH-001", "net_cash_position", Decimal("0"), ThresholdDirection.BELOW, AlertSeverity.CRITICAL),
    AlertRule("CASH-002", "forecast_deficit_7d", Decimal("5000000"), ThresholdDirection.ABOVE, AlertSeverity.HIGH),
    AlertRule("FX-001", "unhedged_fx_exposure", Decimal("10000000"), ThresholdDirection.ABOVE, AlertSeverity.HIGH),
    AlertRule("FX-002", "unhedged_fx_exposure", Decimal("20000000"), ThresholdDirection.ABOVE, AlertSeverity.CRITICAL),
    AlertRule("IR-001", "dv01", Decimal("500000"), ThresholdDirection.ABOVE, AlertSeverity.HIGH),
    AlertRule("CP-001", "counterparty_concentration", Decimal("0.25"), ThresholdDirection.ABOVE, AlertSeverity.MEDIUM),
)


class ThresholdResult(TreasuryBaseModel):
    """Outcome of a single check_threshold call."""

    metric: str
    value: ExactDecimal
    threshold: ExactDecimal
    direction: ThresholdDirection
    breached: bool


class BreachMagnitude(TreasuryBaseModel):
    """How far a value sits from its threshold, in absolute and relative terms."""

    absolute: ExactDecimal
    relative_pct: ExactDecimal


@tool
def check_threshold(value: Decimal, threshold: Decimal, direction: ThresholdDirection) -> ThresholdResult:
    """Whether value breaches threshold in the given direction."""
    if direction == ThresholdDirection.ABOVE:
        breached = value > threshold
    elif direction == ThresholdDirection.BELOW:
        breached = value < threshold
    else:
        raise ToolError(f"unknown direction: {direction}")

    return ThresholdResult(metric="", value=value, threshold=threshold, direction=direction, breached=breached)


@tool
def calculate_breach_magnitude(value: Decimal, threshold: Decimal) -> BreachMagnitude:
    """How far value is from threshold, in absolute and relative terms."""
    if threshold == 0:
        raise ToolError("threshold must not be zero (relative magnitude is undefined)")

    absolute = value - threshold
    relative_pct = (absolute / abs(threshold)) * Decimal("100")
    return BreachMagnitude(absolute=absolute, relative_pct=relative_pct)


@tool
def classify_alert_severity(breach: ThresholdResult) -> AlertSeverity:
    """Generic magnitude-based severity classification for a breach that
    isn't tied to one of DEFAULT_ALERT_RULES's fixed severities.

    breach.breached is already direction-aware (computed by check_threshold,
    correctly handling ABOVE vs. BELOW), so severity here is driven purely
    by how far past the threshold the value is, as a % of the threshold:
    not breached -> INFO, >0% -> LOW, >=10% -> MEDIUM, >=25% -> HIGH,
    >=50% -> CRITICAL.
    """
    if not breach.breached:
        return AlertSeverity.INFO
    if breach.threshold == 0:
        # e.g. CASH-001 (net cash position < 0): no meaningful % magnitude
        # against a zero threshold, and breaching an absolute zero bound is
        # inherently severe.
        return AlertSeverity.CRITICAL

    magnitude = abs((breach.value - breach.threshold) / breach.threshold) * Decimal("100")
    if magnitude >= Decimal("50"):
        return AlertSeverity.CRITICAL
    if magnitude >= Decimal("25"):
        return AlertSeverity.HIGH
    if magnitude >= Decimal("10"):
        return AlertSeverity.MEDIUM
    return AlertSeverity.LOW


@tool
def evaluate_alert_rules(
    metrics: dict[str, Decimal], rules: tuple[AlertRule, ...] = DEFAULT_ALERT_RULES
) -> list[AlertEvent]:
    """Evaluate every rule whose metric is present in `metrics`; return one
    AlertEvent per breach.
    """
    if not metrics:
        raise ToolError("metrics must not be empty")

    now = datetime.now(timezone.utc)
    events: list[AlertEvent] = []
    for rule in rules:
        if rule.metric not in metrics:
            continue
        value = metrics[rule.metric]
        result = check_threshold(value, rule.threshold, rule.direction)
        if not result.breached:
            continue
        events.append(
            AlertEvent(
                rule_id=rule.rule_id,
                metric=rule.metric,
                threshold=rule.threshold,
                actual_value=value,
                severity=rule.severity,
                message=(
                    f"{rule.metric} = {value} breaches {rule.rule_id} "
                    f"({rule.direction.value} {rule.threshold})"
                ),
                timestamp=now,
            )
        )
    return events


@tool
def get_alert_history(log_path: str) -> list[AlertEvent]:
    """Read previously logged ALERT audit entries back out for deduplication.

    Tolerates a missing file (treated as "no history yet") but raises
    ToolError on a corrupt (non-JSONL) file.
    """
    path = Path(log_path)
    if not path.exists():
        return []

    events: list[AlertEvent] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = AuditEntry(**json.loads(line))
                if entry.event_type.value == "ALERT" and "alert" in entry.payload:
                    events.append(AlertEvent(**entry.payload["alert"]))
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        raise ToolError(f"could not parse alert history at {log_path}: {exc}") from exc

    return events
