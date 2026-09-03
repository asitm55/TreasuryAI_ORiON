"""Tests for tools/analytics.py."""

from datetime import date
from decimal import Decimal

import pytest

from core.tool_registry import ToolError
from tools.analytics import (
    benchmark_metrics,
    calculate_kpi_scores,
    calculate_trend,
    calculate_variance_analysis,
    generate_period_summary,
    rank_priorities,
)


# --- calculate_kpi_scores --------------------------------------------------------


def test_calculate_kpi_scores_flags_below_target():
    scorecard = calculate_kpi_scores({"dpo": Decimal("40.5")}, {"dpo": Decimal("45")})
    assert scorecard.metrics["dpo"].on_target is False
    assert scorecard.metrics["dpo"].variance_pct < 0


def test_calculate_kpi_scores_flags_at_or_above_target():
    scorecard = calculate_kpi_scores({"dso": Decimal("48.7")}, {"dso": Decimal("45")})
    assert scorecard.metrics["dso"].on_target is True


def test_calculate_kpi_scores_rejects_empty_metrics():
    with pytest.raises(ToolError):
        calculate_kpi_scores({}, {})


def test_calculate_kpi_scores_rejects_missing_target():
    with pytest.raises(ToolError):
        calculate_kpi_scores({"dso": Decimal("48.7")}, {})


def test_calculate_kpi_scores_rejects_zero_target():
    with pytest.raises(ToolError):
        calculate_kpi_scores({"dso": Decimal("48.7")}, {"dso": Decimal("0")})


# --- calculate_trend --------------------------------------------------------------


def test_calculate_trend_detects_upward_slope():
    series = [(date(2026, m, 1), Decimal(str(100 + m * 10))) for m in range(6, 10)]
    result = calculate_trend(series, metric_name="dso")
    assert result.metric_name == "dso"
    assert result.direction.value == "UP"
    assert result.magnitude > 0


def test_calculate_trend_detects_downward_slope():
    series = [(date(2026, m, 1), Decimal(str(200 - m * 10))) for m in range(6, 10)]
    result = calculate_trend(series)
    assert result.direction.value == "DOWN"


def test_calculate_trend_detects_flat_series():
    series = [(date(2026, m, 1), Decimal("100")) for m in range(6, 10)]
    result = calculate_trend(series)
    assert result.direction.value == "FLAT"
    assert result.magnitude == 0


def test_calculate_trend_rejects_short_series():
    with pytest.raises(ToolError):
        calculate_trend([(date(2026, 6, 1), Decimal("100"))])


# --- benchmark_metrics --------------------------------------------------------------


def test_benchmark_metrics_odd_number_of_peers():
    result = benchmark_metrics("dso", Decimal("48.7"), [Decimal("38"), Decimal("42"), Decimal("55")])
    assert result.peer_median == Decimal("42")
    # 2 of 3 peers (38, 42) are <= 48.7; 55 is not.
    assert result.percentile_rank == Decimal("200") / 3


def test_benchmark_metrics_even_number_of_peers():
    result = benchmark_metrics("dso", Decimal("48.7"), [Decimal("38"), Decimal("42"), Decimal("50"), Decimal("55")])
    assert result.peer_median == Decimal("46")


def test_benchmark_metrics_rejects_empty_peer_set():
    with pytest.raises(ToolError):
        benchmark_metrics("dso", Decimal("48.7"), [])


# --- calculate_variance_analysis -----------------------------------------------------


def test_calculate_variance_analysis_favourable_when_actual_meets_or_beats_budget():
    result = calculate_variance_analysis(Decimal("105"), Decimal("100"))
    assert result.favourable is True
    assert result.variance == Decimal("5")
    assert result.variance_pct == Decimal("5.00")


def test_calculate_variance_analysis_unfavourable_when_actual_below_budget():
    result = calculate_variance_analysis(Decimal("90"), Decimal("100"))
    assert result.favourable is False


def test_calculate_variance_analysis_rejects_zero_budget():
    with pytest.raises(ToolError):
        calculate_variance_analysis(Decimal("100"), Decimal("0"))


# --- generate_period_summary -----------------------------------------------------------


def test_generate_period_summary_averages_metrics_in_window():
    snaps = {
        date(2026, 7, 1): {"dso": Decimal("45")},
        date(2026, 8, 1): {"dso": Decimal("47")},
        date(2026, 9, 1): {"dso": Decimal("48.7")},
        date(2026, 10, 1): {"dso": Decimal("999")},  # outside window
    }
    summary = generate_period_summary(snaps, date(2026, 7, 1), date(2026, 9, 1))
    assert summary.period_count == 3
    assert summary.metric_averages["dso"] == (Decimal("45") + Decimal("47") + Decimal("48.7")) / 3


def test_generate_period_summary_rejects_start_after_end():
    with pytest.raises(ToolError):
        generate_period_summary({date(2026, 7, 1): {"dso": Decimal("1")}}, date(2026, 9, 1), date(2026, 7, 1))


def test_generate_period_summary_rejects_empty_window():
    with pytest.raises(ToolError):
        generate_period_summary({date(2026, 1, 1): {"dso": Decimal("1")}}, date(2026, 7, 1), date(2026, 9, 1))


# --- rank_priorities ---------------------------------------------------------------------


def test_rank_priorities_orders_by_weight_descending():
    ranked = rank_priorities(
        ["LCR near breach", "FX unhedged", "Minor DPO miss"],
        {"LCR near breach": Decimal("90"), "FX unhedged": Decimal("60"), "Minor DPO miss": Decimal("20")},
    )
    assert [r.issue for r in ranked] == ["LCR near breach", "FX unhedged", "Minor DPO miss"]
    assert ranked[0].severity_score == Decimal("100")


def test_rank_priorities_rejects_empty_issues():
    with pytest.raises(ToolError):
        rank_priorities([], {})


def test_rank_priorities_rejects_missing_weight():
    with pytest.raises(ToolError):
        rank_priorities(["LCR near breach"], {})


def test_rank_priorities_rejects_all_non_positive_weights():
    with pytest.raises(ToolError):
        rank_priorities(["A", "B"], {"A": Decimal("0"), "B": Decimal("-5")})
