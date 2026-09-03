"""ARIA — Monitoring & Alerts agent. See agent-specifications.md.

classify_alert_severity's `breach` parameter is a ThresholdResult — an
opaque Pydantic object, not something the LLM can construct from JSON (see
core/tool_registry.py's docstring). It's the *output* of a prior
check_threshold call in the same conversation, so it's injected here from
the agent's own last check_threshold result rather than the model's input,
the same "derived from a prior tool call" pattern as the other agents'
snapshot/positions injections.
"""

from __future__ import annotations

from typing import Any

import tools.alerts  # noqa: F401 - registers this agent's tools on import
from agents.base import BaseAgent
from core.llm_client import LLMResponse
from models.financial import AlertSeverity, TriageRequest
from models.requests import AgentRequest
from models.responses import AriaResponse, ResponseStatus

ARIA_SYSTEM_PROMPT = """You are ARIA, the Monitoring & Alerts agent of TreasuryAI.
Your job is to evaluate current financial metrics against
defined rules and emit clear, actionable alerts.
You do NOT perform root cause analysis — that is ORION's job.
For each breach, state: what metric breached, by how much,
and the recommended triage action (which specialist to consult)."""

_TRIAGE_AGENT_BY_METRIC: dict[str, str] = {
    "lcr": "ATLAS",
    "nsfr": "ATLAS",
    "counterparty_concentration": "ATLAS",
    "net_cash_position": "CORA",
    "forecast_deficit_7d": "CORA",
    "unhedged_fx_exposure": "TARA",
    "dv01": "TARA",
}


def _recommended_agent(metric: str) -> str:
    return _TRIAGE_AGENT_BY_METRIC.get(metric, "ORION")


class AriaAgent(BaseAgent):
    agent_id = "ARIA"
    display_name = "Aria — Monitoring & Alerts"
    system_prompt = ARIA_SYSTEM_PROMPT
    max_tokens = 512
    tool_names = (
        "evaluate_alert_rules",
        "classify_alert_severity",
        "get_alert_history",
        "check_threshold",
        "calculate_breach_magnitude",
    )
    tool_injections = {
        "classify_alert_severity": {"breach": lambda agent, results: agent._last(results, "check_threshold")},
    }

    def _build_response(
        self, request: AgentRequest, llm_response: LLMResponse, reasoning: str, tool_results: dict[str, list[Any]]
    ) -> AriaResponse:
        alerts = self._all_flat(tool_results, "evaluate_alert_rules")

        critical_count = sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL)
        high_count = sum(1 for a in alerts if a.severity == AlertSeverity.HIGH)

        triage_requests = [
            TriageRequest(
                alert=alert,
                recommended_agent=_recommended_agent(alert.metric),
                note=f"{alert.severity.value} breach on {alert.metric}: {alert.message}",
            )
            for alert in alerts
            if alert.severity in (AlertSeverity.CRITICAL, AlertSeverity.HIGH)
        ]

        return AriaResponse(
            agent_id=self.agent_id,
            request_id=request.request_id,
            status=ResponseStatus.COMPLETE,
            reasoning=reasoning or "ARIA evaluated all alert rules against the current snapshot.",
            raw_llm_output=llm_response.content or None,
            alerts=alerts,
            critical_count=critical_count,
            high_count=high_count,
            triage_requests=triage_requests,
        )
