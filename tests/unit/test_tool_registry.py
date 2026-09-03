"""Tests for core/tool_registry.py."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

import pytest

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


def test_dispatch_coerces_string_to_decimal(registry):
    def f(amount: Decimal) -> Decimal:
        return amount * 2

    registry.register(f)
    assert registry.dispatch("f", {"amount": "1.50"}) == Decimal("3.00")


def test_dispatch_coerces_iso_strings_to_date_and_datetime(registry):
    def f(as_of_date: date, as_of_datetime: datetime) -> tuple:
        return as_of_date, as_of_datetime

    registry.register(f)
    result = registry.dispatch("f", {"as_of_date": "2026-09-03", "as_of_datetime": "2026-09-03T12:00:00+00:00"})
    assert result == (date(2026, 9, 3), datetime.fromisoformat("2026-09-03T12:00:00+00:00"))


def test_dispatch_coerces_string_to_enum(registry):
    class Direction(str, Enum):
        UP = "UP"
        DOWN = "DOWN"

    def f(direction: Direction) -> Direction:
        return direction

    registry.register(f)
    result = registry.dispatch("f", {"direction": "UP"})
    assert result is Direction.UP


def test_dispatch_coerces_list_of_decimal(registry):
    def f(values: list[Decimal]) -> Decimal:
        return sum(values, Decimal("0"))

    registry.register(f)
    assert registry.dispatch("f", {"values": ["1.5", "2.5"]}) == Decimal("4.0")


def test_dispatch_coerces_heterogeneous_tuple(registry):
    def f(pair: tuple[date, Decimal]) -> tuple:
        return pair

    registry.register(f)
    result = registry.dispatch("f", {"pair": ["2026-09-03", "1.5"]})
    assert result == (date(2026, 9, 3), Decimal("1.5"))


def test_dispatch_leaves_tuple_alone_when_arg_count_mismatches(registry):
    def f(pair: tuple[date, Decimal]) -> tuple:
        return pair

    registry.register(f)
    # 3 raw values against a 2-type-arg tuple annotation: can't zip meaningfully.
    result = registry.dispatch("f", {"pair": ["2026-09-03", "1.5", "extra"]})
    assert result == ("2026-09-03", "1.5", "extra")


def test_resolved_hints_tolerates_unresolvable_annotation(registry):
    # A annotation referencing a name that doesn't exist in the function's
    # module globals makes typing.get_type_hints() raise; schema generation
    # should degrade gracefully (empty schema) rather than crash.
    ns: dict = {}
    exec("from __future__ import annotations\ndef f(x: DoesNotExist): pass", ns)
    registry.register(ns["f"])
    schema = registry.get_tool_schema("f")
    assert schema["input_schema"]["properties"] == {}


def test_dispatch_coerces_dict_values(registry):
    def f(metrics: dict[str, Decimal]) -> Decimal:
        return sum(metrics.values(), Decimal("0"))

    registry.register(f)
    assert registry.dispatch("f", {"metrics": {"a": "1.5", "b": "2.5"}}) == Decimal("4.0")


def test_dispatch_leaves_untyped_and_none_values_alone(registry):
    def f(a, b: Optional[Decimal] = None) -> tuple:
        return a, b

    registry.register(f)
    assert registry.dispatch("f", {"a": "raw", "b": None}) == ("raw", None)


def test_dispatch_leaves_already_correct_types_alone(registry):
    def f(amount: Decimal, as_of: date) -> tuple:
        return amount, as_of

    registry.register(f)
    result = registry.dispatch("f", {"amount": Decimal("5"), "as_of": date(2026, 1, 1)})
    assert result == (Decimal("5"), date(2026, 1, 1))


def test_dispatch_ignores_kwarg_not_in_signature(registry):
    def f(**kwargs) -> dict:
        return kwargs

    registry.register(f)
    # 'extra' isn't a named parameter (absorbed by **kwargs), so it's passed through unmodified.
    assert registry.dispatch("f", {"extra": "1.5"}) == {"extra": "1.5"}


def test_schema_and_dispatch_work_with_future_annotations_module(registry):
    """Reproduces the real bug: tools/*.py uses `from __future__ import
    annotations`, which stringifies annotations. A function imported from
    such a module must still get a correct schema and coercion.
    """
    import tools.liquidity as liquidity_module

    registry.register(liquidity_module.calculate_lcr, name="calculate_lcr")
    schema = registry.get_tool_schema("calculate_lcr")
    assert schema["input_schema"]["properties"]["hqla"]["type"] == "string"

    result = registry.dispatch("calculate_lcr", {"hqla": "52500000", "net_cash_outflows_30d": "37500000"})
    assert result.ratio == Decimal("1.4")


def test_get_tool_returns_the_raw_function(registry):
    def f(x: int) -> int:
        return x

    registry.register(f)
    assert registry.get_tool("f") is f


def test_get_tool_unknown_raises(registry):
    with pytest.raises(ToolNotFoundError):
        registry.get_tool("does_not_exist")


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
