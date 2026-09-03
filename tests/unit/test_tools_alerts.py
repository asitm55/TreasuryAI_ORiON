"""Tests for tools/alerts.py."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from core.tool_registry import ToolError
from models.audit import AuditEntry, EventType
from models.financial import AlertSeverity
from tools.alerts import (
    DEFAULT_ALERT_RULES,
    ThresholdDirection,
    calculate_breach_magnitude,
    check_threshold,
    classify_alert_severity,
    evaluate_alert_rules,
    get_alert_history,
)


# --- check_threshold --------------------------------------------------------


def test_check_threshold_above_breach():
    result = check_threshold(Decimal("12000000"), Decimal("10000000"), ThresholdDirection.ABOVE)
    assert result.breached is True


def test_check_threshold_above_no_breach():
    result = check_threshold(Decimal("8000000"), Decimal("10000000"), ThresholdDirection.ABOVE)
    assert result.breached is False


def test_check_threshold_below_breach():
    result = check_threshold(Decimal("1.074"), Decimal("1.10"), ThresholdDirection.BELOW)
    assert result.breached is True


def test_check_threshold_below_no_breach():
    result = check_threshold(Decimal("1.40"), Decimal("1.10"), ThresholdDirection.BELOW)
    assert result.breached is False


def test_check_threshold_rejects_unknown_direction():
    with pytest.raises(ToolError):
        check_threshold(Decimal("1"), Decimal("1"), "SIDEWAYS")


# --- calculate_breach_magnitude ----------------------------------------------


def test_calculate_breach_magnitude_computes_signed_values():
    result = calculate_breach_magnitude(Decimal("1.074"), Decimal("1.10"))
    assert result.absolute == Decimal("-0.026")
    assert round(result.relative_pct, 2) == Decimal("-2.36")


def test_calculate_breach_magnitude_rejects_zero_threshold():
    with pytest.raises(ToolError):
        calculate_breach_magnitude(Decimal("1"), Decimal("0"))


# --- classify_alert_severity -------------------------------------------------


def test_classify_alert_severity_info_when_not_breached():
    result = check_threshold(Decimal("1.40"), Decimal("1.10"), ThresholdDirection.BELOW)
    assert classify_alert_severity(result) == AlertSeverity.INFO


def test_classify_alert_severity_critical_when_zero_threshold_breached():
    result = check_threshold(Decimal("-500"), Decimal("0"), ThresholdDirection.BELOW)
    assert classify_alert_severity(result) == AlertSeverity.CRITICAL


@pytest.mark.parametrize(
    "value,threshold,expected",
    [
        (Decimal("10500000"), Decimal("10000000"), AlertSeverity.LOW),      # 5% over
        (Decimal("11500000"), Decimal("10000000"), AlertSeverity.MEDIUM),   # 15% over
        (Decimal("13000000"), Decimal("10000000"), AlertSeverity.HIGH),     # 30% over
        (Decimal("16000000"), Decimal("10000000"), AlertSeverity.CRITICAL), # 60% over
    ],
)
def test_classify_alert_severity_magnitude_bands(value, threshold, expected):
    result = check_threshold(value, threshold, ThresholdDirection.ABOVE)
    assert classify_alert_severity(result) == expected


def test_classify_alert_severity_below_direction_is_sign_correct():
    # A BELOW breach must be classified as a breach, not silently treated as
    # INFO just because (value - threshold) is negative.
    result = check_threshold(Decimal("0.50"), Decimal("1.10"), ThresholdDirection.BELOW)  # 54.5% under
    assert classify_alert_severity(result) == AlertSeverity.CRITICAL


# --- evaluate_alert_rules ----------------------------------------------------


def test_evaluate_alert_rules_fires_expected_rules_for_stressed_lcr():
    metrics = {"lcr": Decimal("1.074"), "nsfr": Decimal("1.187")}
    events = evaluate_alert_rules(metrics)
    rule_ids = {e.rule_id for e in events}
    assert rule_ids == {"LIQ-001", "LIQ-002"}
    liq001 = next(e for e in events if e.rule_id == "LIQ-001")
    assert liq001.severity == AlertSeverity.CRITICAL


def test_evaluate_alert_rules_fires_fx_001_for_fx_shock_exposure():
    events = evaluate_alert_rules({"unhedged_fx_exposure": Decimal("12000000")})
    assert len(events) == 1
    assert events[0].rule_id == "FX-001"


def test_evaluate_alert_rules_no_breach_when_healthy():
    events = evaluate_alert_rules({"lcr": Decimal("1.40"), "nsfr": Decimal("1.187")})
    assert events == []


def test_evaluate_alert_rules_ignores_metrics_not_in_rule_table():
    events = evaluate_alert_rules({"some_unrelated_metric": Decimal("999")})
    assert events == []


def test_evaluate_alert_rules_rejects_empty_metrics():
    with pytest.raises(ToolError):
        evaluate_alert_rules({})


def test_default_alert_rules_cover_the_documented_rule_ids():
    rule_ids = {r.rule_id for r in DEFAULT_ALERT_RULES}
    assert rule_ids == {"LIQ-001", "LIQ-002", "LIQ-003", "CASH-001", "CASH-002", "FX-001", "FX-002", "IR-001", "CP-001"}


# --- get_alert_history --------------------------------------------------------


def test_get_alert_history_returns_empty_for_missing_file(tmp_path):
    assert get_alert_history(str(tmp_path / "missing.jsonl")) == []


def test_get_alert_history_reads_logged_alerts(tmp_path):
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc),
        session_id="s1",
        agent_id="ARIA",
        event_type=EventType.ALERT,
        payload={
            "alert": {
                "rule_id": "LIQ-001",
                "metric": "lcr",
                "threshold": "1.10",
                "actual_value": "1.074",
                "severity": "CRITICAL",
                "message": "m",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "acknowledged": False,
            }
        },
    )
    log_path = tmp_path / "log.jsonl"
    log_path.write_text(entry.model_dump_json() + "\n", encoding="utf-8")

    history = get_alert_history(str(log_path))
    assert len(history) == 1
    assert history[0].rule_id == "LIQ-001"


def test_get_alert_history_skips_non_alert_entries(tmp_path):
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc), session_id="s1", agent_id="ATLAS",
        event_type=EventType.TOOL_CALL, payload={"tool": "calculate_lcr"},
    )
    log_path = tmp_path / "log.jsonl"
    log_path.write_text(entry.model_dump_json() + "\n", encoding="utf-8")
    assert get_alert_history(str(log_path)) == []


def test_get_alert_history_skips_blank_lines(tmp_path):
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc), session_id="s1", agent_id="ARIA",
        event_type=EventType.ALERT,
        payload={
            "alert": {
                "rule_id": "LIQ-001", "metric": "lcr", "threshold": "1.10",
                "actual_value": "1.074", "severity": "CRITICAL", "message": "m",
                "timestamp": datetime.now(timezone.utc).isoformat(), "acknowledged": False,
            }
        },
    )
    log_path = tmp_path / "log.jsonl"
    log_path.write_text("\n" + entry.model_dump_json() + "\n\n", encoding="utf-8")
    assert len(get_alert_history(str(log_path))) == 1


def test_get_alert_history_rejects_corrupt_file(tmp_path):
    log_path = tmp_path / "corrupt.jsonl"
    log_path.write_text("not valid json\n", encoding="utf-8")
    with pytest.raises(ToolError):
        get_alert_history(str(log_path))
