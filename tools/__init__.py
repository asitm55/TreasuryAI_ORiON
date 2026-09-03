"""Importing tools registers every @tool-decorated function with
core.tool_registry.default_registry.
"""

from tools import alerts, analytics, cash_flow, liquidity, risk  # noqa: F401
