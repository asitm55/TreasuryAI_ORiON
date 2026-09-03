"""FIRA — Financial Intelligence specialist. See agent-specifications.md.

Unlike ATLAS/CORA/TARA, none of FIRA's tools take a TreasurySnapshot or
other agent-injected data — analytics.py's functions operate purely on
metrics/time-series the caller supplies, since KPI targets and peer
benchmarks are policy inputs, not data this project's synthetic layer owns
(see tools/analytics.py's module docstring). FIRA also never gates on
approval — its FiraResponse has no recommendations field at all.
"""

from __future__ import annotations

from typing import Any

import tools.analytics  # noqa: F401 - registers this agent's tools on import
from agents.base import BaseAgent
from core.llm_client import LLMResponse
from models.financial import BenchmarkResult, KPIScorecard
from models.requests import AgentRequest
from models.responses import FiraResponse, ResponseStatus

FIRA_SYSTEM_PROMPT = """You are FIRA, the Financial Intelligence specialist of TreasuryAI.
Your role is to provide analytical context and clear narrative
around treasury performance data. You interpret outputs from
other agents and from your own tools, producing clear summaries
for executive audiences. You do NOT perform risk or liquidity
calculations; refer those questions to TARA or ATLAS.
All outputs are informational — not recommendations requiring approval."""

_EMPTY_SCORECARD = KPIScorecard(metrics={})
_EMPTY_BENCHMARK = BenchmarkResult(
    metric_name="unavailable", entity_value=0, peer_median=0, percentile_rank=0, commentary="No benchmark computed."
)


class FiraAgent(BaseAgent):
    """Financial Intelligence specialist: KPI scoring, trends, benchmarking, narrative."""

    agent_id = "FIRA"
    display_name = "Fira — Financial Intelligence"
    system_prompt = FIRA_SYSTEM_PROMPT
    max_tokens = 1536
    tool_names = (
        "calculate_kpi_scores",
        "calculate_trend",
        "benchmark_metrics",
        "calculate_variance_analysis",
        "generate_period_summary",
        "rank_priorities",
    )

    def _build_response(
        self, request: AgentRequest, llm_response: LLMResponse, reasoning: str, tool_results: dict[str, list[Any]]
    ) -> FiraResponse:
        kpi_scorecard = self._last(tool_results, "calculate_kpi_scores") or _EMPTY_SCORECARD
        trend_insights = self._all(tool_results, "calculate_trend")
        benchmark_comparison = self._last(tool_results, "benchmark_metrics") or _EMPTY_BENCHMARK
        priority_issues = self._all_flat(tool_results, "rank_priorities")

        narrative = reasoning or "FIRA has no further commentary for this period."

        return FiraResponse(
            agent_id=self.agent_id,
            request_id=request.request_id,
            status=ResponseStatus.COMPLETE,
            reasoning=narrative,
            raw_llm_output=llm_response.content or None,
            kpi_scorecard=kpi_scorecard,
            trend_insights=trend_insights,
            benchmark_comparison=benchmark_comparison,
            executive_narrative=narrative,
            priority_issues=priority_issues,
        )
