"""ORION — Orchestrator. See agent-specifications.md.

ORION doesn't subclass BaseAgent: its "tools" aren't tools/*.py calculations
dispatched through an LLM tool-use loop. route_to_agent is explicitly "not
an LLM tool; handled in code" per the spec — intent classification and
specialist routing are deterministic Python, not something the model
chooses. summarise_responses is "an LLM tool that asks the model to
synthesise specialist outputs"; implemented here as a single plain
(non-tool-use) LLM completion over the specialists' own reasoning text,
since producing a paragraph of prose doesn't need the structured-output
machinery submit_recommendation exists for (see agents/base.py) — there's
nothing to validate a schema against.

Boundaries from the spec, enforced structurally rather than by convention:
- "Must not perform financial analysis directly" — OrionAgent has no
  tool_registry access at all, only specialist AgentResponses.
- "Must not invoke ARIA directly" — _classify_intent's routing table only
  ever names ATLAS/CORA/TARA/FIRA; ARIA reaches ORION only via the separate
  triage_alert() entry point, matching the Agent Interaction Matrix's
  ARIA -> ORION (triage request) direction.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.audit import AuditLogger
from core.llm_client import LLMResponse
from agents.base import BaseAgent
from models.audit import AuditEntry, EventType
from models.financial import TriageRequest
from models.requests import AgentRequest
from models.responses import AgentResponse, OrionResponse, ResponseStatus

ORION_SYSTEM_PROMPT = """You are ORION, the orchestrator of the TreasuryAI platform.
Your job is to understand the operator's request, decide which
specialist agents are needed, and synthesise their findings into
a clear, actionable briefing.

You NEVER perform financial calculations yourself.
You ALWAYS route quantitative questions to the appropriate specialist.
When any specialist flags a recommendation as PENDING_APPROVAL,
you MUST surface that status in your final response."""

# ATLAS/CORA/TARA/FIRA only — ORION must never invoke ARIA directly (it
# reaches ORION the other way, via triage_alert()).
_INTENT_ROUTES: list[tuple[tuple[str, ...], list[str]]] = [
    (("stress",), ["ATLAS", "TARA"]),
    (("brief", "daily"), ["ATLAS", "CORA", "FIRA"]),
    (("fx", "hedg", "currency"), ["TARA", "FIRA"]),
    (("liquidity", "lcr", "nsfr"), ["ATLAS"]),
    (("cash", "forecast", "working capital", "payment"), ["CORA"]),
    (("risk", "var", "exposure", "counterparty", "duration"), ["TARA"]),
    (("kpi", "benchmark", "trend", "performance", "priorit"), ["FIRA"]),
]


class OrionAgent:
    """Orchestrator: classifies intent, routes to specialists, synthesises a briefing."""

    agent_id = "ORION"
    display_name = "Orion — Orchestrator"
    system_prompt = ORION_SYSTEM_PROMPT
    max_tokens = 2048

    def __init__(self, llm_client, specialists: dict[str, BaseAgent], audit_logger: AuditLogger):
        self.llm_client = llm_client
        self.specialists = specialists
        self.audit_logger = audit_logger
        # Observability only (not part of OrionResponse): the raw specialist
        # responses from the most recent run(), for tests/UIs that want to
        # inspect e.g. a specialist's stress_results directly.
        self.last_specialist_responses: dict[str, AgentResponse] = {}

    def _classify_intent(self, query: str) -> list[str]:
        q = query.lower()
        for keywords, agent_ids in _INTENT_ROUTES:
            if any(keyword in q for keyword in keywords):
                return agent_ids
        return ["FIRA"]  # unknown intent: fall back to a general analytical query

    def _invoke_specialists(self, agent_ids: list[str], request: AgentRequest) -> dict[str, AgentResponse]:
        return {agent_id: self.specialists[agent_id].run(request) for agent_id in agent_ids if agent_id in self.specialists}

    def _synthesise(self, request: AgentRequest, responses: dict[str, AgentResponse]) -> OrionResponse:
        if not responses:
            final_briefing = "No specialist was available to answer this request."
            status = ResponseStatus.ERROR
        else:
            report = "\n\n".join(f"[{agent_id}] {resp.reasoning}" for agent_id, resp in responses.items())
            llm_response: LLMResponse = self.llm_client.complete(
                messages=[{"role": "user", "content": f"{request.user_query}\n\nSpecialist findings:\n{report}"}],
                system=self.system_prompt,
                max_tokens=self.max_tokens,
            )
            final_briefing = llm_response.content or "Specialists reported no material findings."

            if any(r.status == ResponseStatus.ERROR for r in responses.values()):
                status = ResponseStatus.ERROR
            elif any(r.status == ResponseStatus.PENDING_APPROVAL for r in responses.values()):
                status = ResponseStatus.PENDING_APPROVAL
            else:
                status = ResponseStatus.COMPLETE

        recommendations = [
            rec for resp in responses.values() for rec in (getattr(resp, "recommendations", None) or [])
        ]

        return OrionResponse(
            agent_id=self.agent_id,
            request_id=request.request_id,
            status=status,
            reasoning=f"Routed to {list(responses.keys())} based on the request and synthesised their findings.",
            session_id=request.session_id,
            agents_invoked=list(responses.keys()),
            specialist_summaries={agent_id: resp.reasoning for agent_id, resp in responses.items()},
            final_briefing=final_briefing,
            recommendations=recommendations,
            approval_required=status == ResponseStatus.PENDING_APPROVAL,
        )

    def _log_response(self, request: AgentRequest, response: OrionResponse) -> None:
        self.audit_logger.log(
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                session_id=request.session_id,
                agent_id=self.agent_id,
                event_type=EventType.AGENT_RESPONSE,
                payload=response.model_dump(mode="json"),
            )
        )

    def run(self, request: AgentRequest) -> OrionResponse:
        """Classify intent, invoke the relevant specialists, and synthesise their findings."""
        agent_ids = self._classify_intent(request.user_query)
        responses = self._invoke_specialists(agent_ids, request)
        self.last_specialist_responses = responses
        response = self._synthesise(request, responses)
        self._log_response(request, response)
        return response

    def triage_alert(self, triage_request: TriageRequest, request: AgentRequest) -> OrionResponse:
        """Entry point for ARIA -> ORION triage requests (see Agent
        Interaction Matrix). ORION never invokes ARIA; ARIA invokes this.
        """
        agent_ids = [triage_request.recommended_agent] if triage_request.recommended_agent in self.specialists else []
        responses = self._invoke_specialists(agent_ids, request)
        self.last_specialist_responses = responses
        response = self._synthesise(request, responses)
        self._log_response(request, response)
        return response
