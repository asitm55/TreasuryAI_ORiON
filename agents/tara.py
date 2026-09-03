"""TARA — Treasury Risk specialist. See agent-specifications.md."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import tools.risk  # noqa: F401 - registers this agent's tools on import
from agents.base import BaseAgent
from core.llm_client import LLMResponse
from models.financial import RateSensitivity, RiskSummary, VaRMetrics
from models.requests import AgentRequest
from models.responses import ResponseStatus, TaraResponse

TARA_SYSTEM_PROMPT = """You are TARA, the Treasury Risk specialist of TreasuryAI.
You identify and quantify financial risks in the treasury portfolio.
Use only the tools provided for all calculations.
Express risk in clear terms: exposure amounts, probability ranges,
and potential P&L impact. Always note confidence limitations
in model outputs. Hedging recommendations must be marked
PENDING_APPROVAL and framed as options, not directives.

When you have a recommendation, call submit_recommendation with
requires_approval=true for any hedging or risk-mitigation action.

calculate_fx_exposure, calculate_counterparty_exposure, and
calculate_interest_rate_sensitivity work directly off the current snapshot.
calculate_var, calculate_duration, and calculate_hedge_effectiveness need a
historical returns series, cash-flow schedule, or hedge/unhedged amounts
that only the operator can supply — do not call them unless the operator
has given you that data in the conversation."""

_ZERO_RATE_SENSITIVITY = RateSensitivity(dv01=Decimal("0"), modified_duration=Decimal("0"), parallel_shift_impact=Decimal("0"))
_ZERO_VAR_METRICS = VaRMetrics(confidence=Decimal("0.95"), horizon_days=1, var_1d=Decimal("0"), var_10d=Decimal("0"), expected_shortfall=Decimal("0"))


class TaraAgent(BaseAgent):
    agent_id = "TARA"
    display_name = "Tara — Treasury Risk"
    system_prompt = TARA_SYSTEM_PROMPT
    max_tokens = 1024
    tool_names = (
        "calculate_fx_exposure",
        "calculate_var",
        "calculate_duration",
        "calculate_hedge_effectiveness",
        "run_scenario_analysis",
        "calculate_counterparty_exposure",
        "calculate_interest_rate_sensitivity",
        "submit_recommendation",
    )
    tool_injections = {
        "calculate_fx_exposure": {"snapshot": lambda agent, _: agent.snapshot},
        "run_scenario_analysis": {"snapshot": lambda agent, _: agent.snapshot},
        "calculate_counterparty_exposure": {"snapshot": lambda agent, _: agent.snapshot},
        "calculate_interest_rate_sensitivity": {"portfolio": lambda agent, _: list(agent.snapshot.investment_positions)},
    }

    def _build_response(
        self, request: AgentRequest, llm_response: LLMResponse, reasoning: str, tool_results: dict[str, list[Any]]
    ) -> TaraResponse:
        fx_exposures = self._all_flat(tool_results, "calculate_fx_exposure")
        var_metrics = self._last(tool_results, "calculate_var")
        rate_sensitivity = self._last(tool_results, "calculate_interest_rate_sensitivity") or _ZERO_RATE_SENSITIVITY
        counterparty_risks = self._all_flat(tool_results, "calculate_counterparty_exposure")
        scenario_results = self._all_flat(tool_results, "run_scenario_analysis")
        recommendations = self._all(tool_results, "submit_recommendation")

        total_fx_exposure = sum((abs(e.net) for e in fx_exposures), Decimal("0"))
        top_risks = [
            f"{e.currency_pair} net exposure {e.net}"
            for e in sorted(fx_exposures, key=lambda e: abs(e.net), reverse=True)[:3]
        ] or ["No material FX risks identified"]
        risk_summary = RiskSummary(
            total_fx_exposure=total_fx_exposure,
            var_1d=var_metrics.var_1d if var_metrics else Decimal("0"),
            top_risks=top_risks,
        )

        status = (
            ResponseStatus.PENDING_APPROVAL
            if any(r.requires_approval for r in recommendations)
            else ResponseStatus.COMPLETE
        )

        return TaraResponse(
            agent_id=self.agent_id,
            request_id=request.request_id,
            status=status,
            reasoning=reasoning or "TARA completed its risk review.",
            raw_llm_output=llm_response.content or None,
            risk_summary=risk_summary,
            fx_exposures=fx_exposures,
            var_metrics=var_metrics or _ZERO_VAR_METRICS,
            rate_sensitivity=rate_sensitivity,
            counterparty_risks=counterparty_risks,
            scenario_results=scenario_results,
            recommendations=recommendations,
        )
