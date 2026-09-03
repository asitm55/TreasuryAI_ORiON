"""KPI scoring, trend, benchmarking, variance, and prioritisation tools.

These are generic analytical functions — they take metrics/time-series data
supplied by the caller rather than a TreasurySnapshot directly, since KPI
targets and peer benchmarks are policy inputs, not something the synthetic
data layer owns.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.tool_registry import ToolError, tool
from models.base import ExactDecimal, TreasuryBaseModel
from models.financial import (
    BenchmarkResult,
    KPIScore,
    KPIScorecard,
    PriorityIssue,
    TrendDirection,
    TrendInsight,
)


class VarianceAnalysis(TreasuryBaseModel):
    actual: ExactDecimal
    budget: ExactDecimal
    variance: ExactDecimal
    variance_pct: ExactDecimal
    favourable: bool


class PeriodSummary(TreasuryBaseModel):
    start: date
    end: date
    period_count: int
    metric_averages: dict[str, ExactDecimal]


@tool
def calculate_kpi_scores(metrics: dict[str, Decimal], targets: dict[str, Decimal]) -> KPIScorecard:
    """Score each metric against its target. variance_pct = (value-target)/target."""
    if not metrics:
        raise ToolError("metrics must not be empty")
    missing_targets = metrics.keys() - targets.keys()
    if missing_targets:
        raise ToolError(f"missing targets for metrics: {sorted(missing_targets)}")

    scores: dict[str, KPIScore] = {}
    for name, value in metrics.items():
        target = targets[name]
        if target == 0:
            raise ToolError(f"target for '{name}' must not be zero")
        variance_pct = (value - target) / abs(target) * Decimal("100")
        scores[name] = KPIScore(value=value, target=target, variance_pct=variance_pct, on_target=value >= target)
    return KPIScorecard(metrics=scores)


@tool
def calculate_trend(time_series: list[tuple[date, Decimal]], metric_name: str = "series") -> TrendInsight:
    """Simple linear trend (least-squares slope) and direction for a metric's
    time series.
    """
    if len(time_series) < 2:
        raise ToolError("time_series must have at least 2 points")

    ordered = sorted(time_series, key=lambda pair: pair[0])
    xs = [Decimal(i) for i in range(len(ordered))]
    ys = [value for _, value in ordered]

    n = Decimal(len(ordered))
    mean_x = sum(xs, Decimal("0")) / n
    mean_y = sum(ys, Decimal("0")) / n

    numerator = sum(((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)), Decimal("0"))
    denominator = sum(((x - mean_x) ** 2 for x in xs), Decimal("0"))

    slope = numerator / denominator if denominator != 0 else Decimal("0")

    if slope > 0:
        direction = TrendDirection.UP
    elif slope < 0:
        direction = TrendDirection.DOWN
    else:
        direction = TrendDirection.FLAT

    return TrendInsight(
        metric_name=metric_name,
        direction=direction,
        magnitude=abs(slope),
        commentary=f"Slope of {slope:.4f} per period across {len(ordered)} observations.",
    )


@tool
def benchmark_metrics(metric_name: str, entity_value: Decimal, peer_values: list[Decimal]) -> BenchmarkResult:
    """Compare a metric to a synthetic peer set: median and percentile rank."""
    if not peer_values:
        raise ToolError("peer_values must not be empty")

    sorted_peers = sorted(peer_values)
    n = len(sorted_peers)
    mid = n // 2
    peer_median = sorted_peers[mid] if n % 2 == 1 else (sorted_peers[mid - 1] + sorted_peers[mid]) / 2

    rank = sum(1 for v in sorted_peers if v <= entity_value)
    percentile_rank = Decimal(rank) / Decimal(n) * Decimal("100")

    return BenchmarkResult(
        metric_name=metric_name,
        entity_value=entity_value,
        peer_median=peer_median,
        percentile_rank=percentile_rank,
        commentary=f"{metric_name} of {entity_value} sits at the {percentile_rank:.0f}th percentile of {n} peers (median {peer_median}).",
    )


@tool
def calculate_variance_analysis(actual: Decimal, budget: Decimal) -> VarianceAnalysis:
    """Budget vs. actual variance for a single metric. Favourable means
    actual came in better than budget (higher revenue or lower cost is
    ambiguous in general, so 'favourable' here simply means actual >= budget
    — callers comparing a cost line should interpret the sign accordingly).
    """
    if budget == 0:
        raise ToolError("budget must not be zero")

    variance = actual - budget
    variance_pct = variance / abs(budget) * Decimal("100")
    return VarianceAnalysis(actual=actual, budget=budget, variance=variance, variance_pct=variance_pct, favourable=actual >= budget)


@tool
def generate_period_summary(snapshots: dict[date, dict[str, Decimal]], start: date, end: date) -> PeriodSummary:
    """Average each metric across snapshots dated within [start, end]."""
    if start > end:
        raise ToolError("start must not be after end")

    in_window = {as_of: metrics for as_of, metrics in snapshots.items() if start <= as_of <= end}
    if not in_window:
        raise ToolError("no snapshots fall within [start, end]")

    metric_names: set[str] = set()
    for metrics in in_window.values():
        metric_names.update(metrics.keys())

    metric_averages: dict[str, Decimal] = {}
    for name in metric_names:
        values = [metrics[name] for metrics in in_window.values() if name in metrics]
        metric_averages[name] = sum(values, Decimal("0")) / len(values)

    return PeriodSummary(start=start, end=end, period_count=len(in_window), metric_averages=metric_averages)


@tool
def rank_priorities(issues: list[str], weights: dict[str, Decimal]) -> list[PriorityIssue]:
    """Sort issues by weighted severity score, highest first.

    weights maps each issue string to a raw severity weight; the returned
    severity_score is that weight normalised to a 0-100 scale against the
    highest weight in the batch.
    """
    if not issues:
        raise ToolError("issues must not be empty")
    missing = set(issues) - weights.keys()
    if missing:
        raise ToolError(f"missing weights for issues: {sorted(missing)}")

    max_weight = max(weights[issue] for issue in issues)
    if max_weight <= 0:
        raise ToolError("at least one issue weight must be positive")

    ranked = sorted(issues, key=lambda issue: weights[issue], reverse=True)
    return [
        PriorityIssue(
            issue=issue,
            category="unclassified",
            severity_score=(weights[issue] / max_weight) * Decimal("100"),
            recommended_owner="ORION",
        )
        for issue in ranked
    ]
