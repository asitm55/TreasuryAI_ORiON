"""CORA — Cash Operations specialist. See agent-specifications.md."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import tools.cash_flow  # noqa: F401 - registers this agent's tools on import
from agents.base import BaseAgent
from core.llm_client import LLMResponse
from models.financial import CashFlowForecast, WorkingCapitalMetrics
from models.financial import CashPosition
from models.requests import AgentRequest
from models.responses import CoraResponse, ResponseStatus

CORA_SYSTEM_PROMPT = """You are CORA, the Cash Operations specialist of TreasuryAI.
Your focus is the near-term (0-30 day) cash position, forecasting,
and working capital. Use the tools provided to analyse patterns
and flag anomalies. You do NOT manage the investment portfolio
or regulatory ratios — refer those questions to ATLAS.
Any recommendation to move, pool, or concentrate cash must
be marked PENDING_APPROVAL.

When you have a recommendation, call submit_recommendation with
requires_approval=true for any action that would move, pool, or
concentrate cash."""


def _empty_forecast() -> CashFlowForecast:
    return CashFlowForecast(entity="Consolidated (USD)", periods=[], inflows=[], outflows=[], net=[])


def _empty_cash_position() -> CashPosition:
    return CashPosition(currency="USD", amount=Decimal("0"), account_id="UNKNOWN", as_of=datetime.now(timezone.utc))


def _empty_working_capital() -> WorkingCapitalMetrics:
    return WorkingCapitalMetrics(dso=Decimal("0"), dpo=Decimal("0"), ccc=Decimal("0"), days_cash_on_hand=Decimal("0"))


class CoraAgent(BaseAgent):
    """Cash Operations specialist: near-term cash forecasting, working capital, sweeps."""

    agent_id = "CORA"
    display_name = "Cora — Cash Operations"
    system_prompt = CORA_SYSTEM_PROMPT
    max_tokens = 1024
    tool_names = (
        "get_cash_flow_forecast",
        "calculate_net_cash_position",
        "analyse_payment_patterns",
        "calculate_working_capital_metrics",
        "detect_anomalies",
        "calculate_sweep_opportunity",
        "calculate_forecast_variance",
        "submit_recommendation",
    )
    tool_injections = {
        "get_cash_flow_forecast": {"snapshot": lambda agent, _: agent.snapshot},
        "calculate_net_cash_position": {"snapshot": lambda agent, _: agent.snapshot},
        "analyse_payment_patterns": {"snapshot": lambda agent, _: agent.snapshot},
        "calculate_working_capital_metrics": {"snapshot": lambda agent, _: agent.snapshot},
        "calculate_sweep_opportunity": {
            "positions": lambda agent, _: [pos for positions in agent.snapshot.cash_positions.values() for pos in positions]
        },
    }

    def _build_response(
        self, request: AgentRequest, llm_response: LLMResponse, reasoning: str, tool_results: dict[str, list[Any]]
    ) -> CoraResponse:
        forecast = self._last(tool_results, "get_cash_flow_forecast") or _empty_forecast()
        net_position = self._last(tool_results, "calculate_net_cash_position") or _empty_cash_position()
        working_capital = self._last(tool_results, "calculate_working_capital_metrics") or _empty_working_capital()
        anomalies = self._all_flat(tool_results, "detect_anomalies")
        sweep_opportunities = self._all_flat(tool_results, "calculate_sweep_opportunity")
        recommendations = self._all(tool_results, "submit_recommendation")

        status = (
            ResponseStatus.PENDING_APPROVAL
            if any(r.requires_approval for r in recommendations)
            else ResponseStatus.COMPLETE
        )

        return CoraResponse(
            agent_id=self.agent_id,
            request_id=request.request_id,
            status=status,
            reasoning=reasoning or "CORA completed its cash operations review.",
            raw_llm_output=llm_response.content or None,
            net_cash_position=net_position,
            forecast_30d=forecast,
            working_capital=working_capital,
            anomalies=anomalies,
            sweep_opportunities=sweep_opportunities,
            recommendations=recommendations,
        )
