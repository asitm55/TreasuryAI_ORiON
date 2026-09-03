"""Tests for core/tool_registry.py."""

from decimal import Decimal
from typing import Optional

import pytest

from enum import Enum

from core.tool_registry import ToolNotFoundError, ToolRegistry


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


def test_register_and_dispatch(registry):
    def add(a: int, b: int) -> int:
        """Add two ints."""
        return a + b

    registry.register(add)
    assert registry.dispatch("add", {"a": 2, "b": 3}) == 5


def test_register_with_explicit_name(registry):
    def f(x: int) -> int:
        return x

    registry.register(f, name="custom_name")
    assert registry.list_tools() == ["custom_name"]
    assert registry.dispatch("custom_name", {"x": 5}) == 5


def test_dispatch_unknown_tool_raises(registry):
    with pytest.raises(ToolNotFoundError):
        registry.dispatch("does_not_exist", {})


def test_get_tool_schema_unknown_tool_raises(registry):
    with pytest.raises(ToolNotFoundError):
        registry.get_tool_schema("does_not_exist")


def test_get_tool_schema_uses_docstring_as_description(registry):
    def greet(name: str) -> str:
        """Greet someone by name."""
        return f"hello {name}"

    registry.register(greet)
    schema = registry.get_tool_schema("greet")
    assert schema["name"] == "greet"
    assert schema["description"] == "Greet someone by name."
    assert schema["input_schema"]["properties"]["name"] == {"type": "string"}
    assert schema["input_schema"]["required"] == ["name"]


def test_get_tool_schema_marks_defaulted_params_as_not_required(registry):
    def f(required_arg: str, optional_arg: int = 5) -> None:
        pass

    registry.register(f)
    schema = registry.get_tool_schema("f")
    assert schema["input_schema"]["required"] == ["required_arg"]
    assert "optional_arg" in schema["input_schema"]["properties"]


def test_get_tool_schema_maps_decimal_to_string(registry):
    def f(amount: Decimal) -> Decimal:
        return amount

    registry.register(f)
    schema = registry.get_tool_schema("f")
    assert schema["input_schema"]["properties"]["amount"]["type"] == "string"


def test_get_tool_schema_maps_list_of_primitives(registry):
    def f(values: list[int]) -> int:
        return sum(values)

    registry.register(f)
    schema = registry.get_tool_schema("f")
    assert schema["input_schema"]["properties"]["values"] == {"type": "array", "items": {"type": "integer"}}


def test_get_tool_schema_maps_optional_to_underlying_type(registry):
    def f(note: Optional[str] = None) -> None:
        pass

    registry.register(f)
    schema = registry.get_tool_schema("f")
    assert schema["input_schema"]["properties"]["note"] == {"type": "string"}
    assert schema["input_schema"]["required"] == []


def test_get_tool_schema_excludes_non_json_representable_params(registry):
    class Opaque:
        pass

    def f(snapshot: Opaque, amount: Decimal) -> Decimal:
        return amount

    registry.register(f)
    schema = registry.get_tool_schema("f")
    assert "snapshot" not in schema["input_schema"]["properties"]
    assert "snapshot" not in schema["input_schema"]["required"]
    assert "amount" in schema["input_schema"]["properties"]


def test_get_tool_schema_ignores_var_args_and_kwargs(registry):
    def f(a: int, *args, **kwargs) -> int:
        return a

    registry.register(f)
    schema = registry.get_tool_schema("f")
    assert list(schema["input_schema"]["properties"].keys()) == ["a"]


def test_get_tool_schema_untyped_param_gets_empty_schema(registry):
    def f(anything) -> None:
        pass

    registry.register(f)
    schema = registry.get_tool_schema("f")
    assert schema["input_schema"]["properties"]["anything"] == {}


def test_get_tool_schema_maps_enum_to_string_with_values(registry):
    class Direction(str, Enum):
        UP = "UP"
        DOWN = "DOWN"

    def f(direction: Direction) -> None:
        pass

    registry.register(f)
    schema = registry.get_tool_schema("f")
    assert schema["input_schema"]["properties"]["direction"] == {"type": "string", "enum": ["UP", "DOWN"]}


def test_get_tool_schema_maps_dict_param(registry):
    def f(mapping: dict[str, int]) -> None:
        pass

    registry.register(f)
    schema = registry.get_tool_schema("f")
    assert schema["input_schema"]["properties"]["mapping"] == {"type": "object"}


def test_get_tool_schema_excludes_list_of_non_representable_items(registry):
    class Opaque:
        pass

    def f(items: list[Opaque], amount: int) -> None:
        pass

    registry.register(f)
    schema = registry.get_tool_schema("f")
    assert "items" not in schema["input_schema"]["properties"]
    assert "amount" in schema["input_schema"]["properties"]


def test_module_level_tool_get_tool_schema_and_dispatch_use_default_registry():
    from core import tool_registry as reg_module

    @reg_module.tool
    def module_level_add(a: int, b: int) -> int:
        """Add for the default registry."""
        return a + b

    schema = reg_module.get_tool_schema("module_level_add")
    assert schema["name"] == "module_level_add"
    assert reg_module.dispatch("module_level_add", {"a": 4, "b": 6}) == 10


def test_list_tools_is_sorted(registry):
    def z(): pass
    def a(): pass

    registry.register(z)
    registry.register(a)
    assert registry.list_tools() == ["a", "z"]


def test_all_project_tools_register_and_produce_valid_schemas():
    import tools  # noqa: F401 - registers every @tool-decorated function
    from core.tool_registry import default_registry

    expected = {
        "get_cash_position", "calculate_lcr", "calculate_nsfr", "calculate_liquidity_gap",
        "get_investment_portfolio", "run_liquidity_stress", "calculate_concentration_risk",
        "get_cash_flow_forecast", "calculate_net_cash_position", "analyse_payment_patterns",
        "calculate_working_capital_metrics", "detect_anomalies", "calculate_sweep_opportunity",
        "calculate_forecast_variance",
        "calculate_fx_exposure", "calculate_var", "calculate_duration", "calculate_hedge_effectiveness",
        "run_scenario_analysis", "calculate_counterparty_exposure", "calculate_interest_rate_sensitivity",
        "calculate_kpi_scores", "calculate_trend", "benchmark_metrics", "calculate_variance_analysis",
        "generate_period_summary", "rank_priorities",
        "evaluate_alert_rules", "classify_alert_severity", "get_alert_history", "check_threshold",
        "calculate_breach_magnitude",
    }
    registered = set(default_registry.list_tools())
    assert expected <= registered

    for name in expected:
        schema = default_registry.get_tool_schema(name)
        assert schema["name"] == name
        assert isinstance(schema["description"], str) and schema["description"]
        assert schema["input_schema"]["type"] == "object"
