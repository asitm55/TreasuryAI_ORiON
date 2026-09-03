"""ATLAS — Treasury & Liquidity specialist. See agent-specifications.md."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import tools.liquidity  # noqa: F401 - registers this agent's tools on import
from agents.base import BaseAgent
from core.llm_client import LLMResponse
from models.financial import CoverageRatios, LiquidityMetrics
from models.requests import AgentRequest
from models.responses import AtlasResponse, ResponseStatus

ATLAS_SYSTEM_PROMPT = """You are ATLAS, the Treasury & Liquidity specialist of TreasuryAI.
You analyse balance sheet liquidity using the tools provided.
You interpret regulatory ratios (LCR >= 100%, NSFR >= 100%)
and flag breaches or near-breaches as HIGH priority.
You NEVER calculate ratios yourself — always call the appropriate tool.
Recommendations to move funds or adjust portfolio composition
must always be marked PENDING_APPROVAL.

When you have a recommendation, call submit_recommendation with
requires_approval=true for any action that would move funds or change
portfolio composition."""


class AtlasAgent(BaseAgent):
    agent_id = "ATLAS"
    display_name = "Atlas — Treasury & Liquidity"
    system_prompt = ATLAS_SYSTEM_PROMPT
    max_tokens = 1024
    tool_names = (
        "get_cash_position",
        "calculate_lcr",
        "calculate_nsfr",
        "calculate_liquidity_gap",
        "get_investment_portfolio",
        "run_liquidity_stress",
        "calculate_concentration_risk",
        "submit_recommendation",
    )
    tool_injections = {
        "get_cash_position": {"snapshot": lambda agent, _: agent.snapshot},
        "get_investment_portfolio": {"snapshot": lambda agent, _: agent.snapshot},
        "run_liquidity_stress": {"snapshot": lambda agent, _: agent.snapshot},
        "calculate_concentration_risk": {"positions": lambda agent, _: list(agent.snapshot.investment_positions)},
    }

    def _build_response(
        self, request: AgentRequest, llm_response: LLMResponse, reasoning: str, tool_results: dict[str, list[Any]]
    ) -> AtlasResponse:
        lcr_result = self._last(tool_results, "calculate_lcr")
        nsfr_result = self._last(tool_results, "calculate_nsfr")
        gaps = self._all_flat(tool_results, "calculate_liquidity_gap")
        stress_result = self._last(tool_results, "run_liquidity_stress")
        recommendations = self._all(tool_results, "submit_recommendation")

        liquidity_metrics = LiquidityMetrics(
            lcr=lcr_result.ratio if lcr_result else Decimal("0"),
            nsfr=nsfr_result.ratio if nsfr_result else Decimal("0"),
            hqla=self.snapshot.hqla,
            net_outflows_30d=self.snapshot.net_cash_outflows_30d,
        )
        coverage_ratios = CoverageRatios(
            lcr_ratio=lcr_result.ratio if lcr_result else Decimal("0"),
            nsfr_ratio=nsfr_result.ratio if nsfr_result else Decimal("0"),
            lcr_compliant=lcr_result.compliant if lcr_result else False,
            nsfr_compliant=nsfr_result.compliant if nsfr_result else False,
        )
        status = (
            ResponseStatus.PENDING_APPROVAL
            if any(r.requires_approval for r in recommendations)
            else ResponseStatus.COMPLETE
        )

        return AtlasResponse(
            agent_id=self.agent_id,
            request_id=request.request_id,
            status=status,
            reasoning=reasoning or "ATLAS completed its liquidity review.",
            raw_llm_output=llm_response.content or None,
            liquidity_metrics=liquidity_metrics,
            coverage_ratios=coverage_ratios,
            gaps_identified=gaps,
            recommendations=recommendations,
            stress_results=stress_result,
        )
