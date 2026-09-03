"""Direct unit tests for OrionAgent._classify_intent's routing table.

The integration tests in tests/integration/test_orion_agent.py only
exercise 2 of the 7 keyword routes end-to-end; this covers every route
directly against the plain classification method.
"""

import pytest

from agents.orion import OrionAgent


@pytest.fixture
def orion() -> OrionAgent:
    return OrionAgent(llm_client=None, specialists={}, audit_logger=None)


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Run a liquidity stress test", ["ATLAS", "TARA"]),
        ("Give me the daily briefing", ["ATLAS", "CORA", "FIRA"]),
        ("What's our daily position?", ["ATLAS", "CORA", "FIRA"]),
        ("Review our FX hedging", ["TARA", "FIRA"]),
        ("Any currency exposure concerns?", ["TARA", "FIRA"]),
        ("What's our LCR right now?", ["ATLAS"]),
        ("Check the NSFR", ["ATLAS"]),
        ("How's our liquidity looking?", ["ATLAS"]),
        ("What's the cash forecast for next week?", ["CORA"]),
        ("Any anomalies in the payment schedule?", ["CORA"]),
        ("What's our counterparty risk exposure?", ["TARA"]),
        ("Show me VaR for the portfolio", ["TARA"]),
        ("What's the duration on our bond book?", ["TARA"]),
        ("How are our KPIs trending?", ["FIRA"]),
        ("Benchmark our DSO against peers", ["FIRA"]),
        ("What are the top priority issues?", ["FIRA"]),
        ("Tell me a joke", ["FIRA"]),  # unknown intent falls back to FIRA
    ],
)
def test_classify_intent_routes_by_keyword(orion, query, expected):
    assert orion._classify_intent(query) == expected


def test_classify_intent_is_case_insensitive(orion):
    assert orion._classify_intent("RUN A STRESS TEST") == ["ATLAS", "TARA"]


def test_classify_intent_never_routes_to_aria(orion):
    queries = [
        "Run a liquidity stress test", "Give me the daily briefing", "Review our FX hedging",
        "What's our LCR?", "Cash forecast please", "Counterparty risk?", "KPI trends?", "random text",
    ]
    for query in queries:
        assert "ARIA" not in orion._classify_intent(query)
