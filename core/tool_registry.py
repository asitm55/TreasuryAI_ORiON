"""Tool registration and dispatch. See ADR-001: LLMs never calculate.

Every function in tools/ is a plain, pure Python function. The @tool
decorator registers it and auto-generates its Anthropic tool-use schema from
its type hints and docstring, so agents (Phase 5) can hand the schema to the
LLM and dispatch() the model's chosen tool call back to the real function.

Parameters whose type isn't representable in JSON (TreasurySnapshot, or a
list/dict of typed domain objects like list[InvestmentPosition]) are left out
of the generated schema — those are always supplied by the calling agent
code from already-loaded data, never chosen by the LLM itself, so they have
no business appearing as something the model can invent values for.

Every tools/*.py module uses `from __future__ import annotations` (PEP 563),
which stringifies all type hints at runtime — inspect.signature(...).annotation
would hand back the literal string "Decimal", not the Decimal class. Both
schema generation and dispatch()'s input coercion resolve real types via
typing.get_type_hints() rather than raw Parameter.annotation.
"""

from __future__ import annotations

import inspect
import types
import typing
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Union, get_args, get_origin

_JSON_PRIMITIVES: dict[type, dict[str, Any]] = {
    str: {"type": "string"},
    bool: {"type": "boolean"},
    int: {"type": "integer"},
    float: {"type": "number"},
    Decimal: {"type": "string", "description": "Decimal amount encoded as a string."},
    date: {"type": "string", "format": "date"},
    datetime: {"type": "string", "format": "date-time"},
}


class ToolError(Exception):
    """Raised by a tools/ function when given invalid input."""


class ToolNotFoundError(KeyError):
    """Raised when get_tool_schema/dispatch/get_tool is asked for an unregistered tool."""

    def __init__(self, name: str, available: list[str]):
        super().__init__(f"Tool '{name}' is not registered. Available: {sorted(available)}")


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _json_schema_for(annotation: Any) -> dict[str, Any] | None:
    """Best-effort JSON schema for a type hint; None if not representable."""
    if annotation is inspect.Parameter.empty:
        return {}

    annotation, _ = _unwrap_optional(annotation)

    if annotation in _JSON_PRIMITIVES:
        return dict(_JSON_PRIMITIVES[annotation])

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return {"type": "string", "enum": [member.value for member in annotation]}

    origin = get_origin(annotation)
    if origin in (list, tuple):
        args = get_args(annotation)
        item_schema = _json_schema_for(args[0]) if args else {}
        if item_schema is None:
            return None
        return {"type": "array", "items": item_schema}

    if origin is dict:
        return {"type": "object"}

    return None


def _coerce_value(value: Any, annotation: Any) -> Any:
    """Reverse of _json_schema_for: convert a JSON-ish value (as an LLM tool
    call, or MockLLMClient fixture, would supply it) back into the Python
    type the target function actually expects — e.g. the string "37500000"
    back into Decimal("37500000"). Without this, a tool call built from a
    JSON schema would hand a plain str straight to code doing arithmetic on
    it.
    """
    if annotation is inspect.Parameter.empty or value is None:
        return value

    annotation, _ = _unwrap_optional(annotation)

    if annotation is Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    if annotation is date:
        return date.fromisoformat(value) if isinstance(value, str) else value
    if annotation is datetime:
        return datetime.fromisoformat(value) if isinstance(value, str) else value
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return value if isinstance(value, annotation) else annotation(value)

    origin = get_origin(annotation)
    if origin is list and isinstance(value, (list, tuple)):
        args = get_args(annotation)
        item_type = args[0] if args else inspect.Parameter.empty
        return [_coerce_value(v, item_type) for v in value]
    if origin is tuple and isinstance(value, (list, tuple)):
        args = get_args(annotation)
        if args and len(args) == len(value):
            return tuple(_coerce_value(v, t) for v, t in zip(value, args))
        return tuple(value)
    if origin is dict and isinstance(value, dict):
        args = get_args(annotation)
        val_type = args[1] if len(args) > 1 else inspect.Parameter.empty
        return {k: _coerce_value(v, val_type) for k, v in value.items()}

    return value


def _resolved_hints(func: Callable[..., Any]) -> dict[str, Any]:
    try:
        return typing.get_type_hints(func)
    except Exception:
        return {}


class ToolRegistry:
    """Maps tool names to Python functions and their auto-generated schemas."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, func: Callable[..., Any], name: str | None = None) -> Callable[..., Any]:
        """Register func under name (or its own __name__). Returns func unchanged."""
        self._tools[name or func.__name__] = func
        return func

    def list_tools(self) -> list[str]:
        """Every registered tool name, sorted."""
        return sorted(self._tools.keys())

    def get_tool(self, name: str) -> Callable[..., Any]:
        """The raw registered function for name."""
        if name not in self._tools:
            raise ToolNotFoundError(name, self.list_tools())
        return self._tools[name]

    def get_tool_schema(self, name: str) -> dict[str, Any]:
        """Anthropic tool-use schema for name, generated from its type hints and docstring."""
        if name not in self._tools:
            raise ToolNotFoundError(name, self.list_tools())
        func = self._tools[name]
        signature = inspect.signature(func)
        hints = _resolved_hints(func)

        properties: dict[str, Any] = {}
        required: list[str] = []
        for param_name, param in signature.parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            annotation = hints.get(param_name, param.annotation)
            schema = _json_schema_for(annotation)
            if schema is None:
                continue
            properties[param_name] = schema
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        description = inspect.getdoc(func) or ""

        return {
            "name": name,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def dispatch(self, name: str, kwargs: dict[str, Any]) -> Any:
        """Call the tool registered as name, coercing kwargs to its real types first."""
        if name not in self._tools:
            raise ToolNotFoundError(name, self.list_tools())
        func = self._tools[name]
        signature = inspect.signature(func)
        hints = _resolved_hints(func)
        coerced = {
            key: _coerce_value(value, hints.get(key, signature.parameters[key].annotation)) if key in signature.parameters else value
            for key, value in kwargs.items()
        }
        return func(**coerced)


default_registry = ToolRegistry()


def tool(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: register func with default_registry. Returns func unchanged."""
    default_registry.register(func)
    return func


def get_tool_schema(name: str) -> dict[str, Any]:
    """Convenience wrapper for default_registry.get_tool_schema."""
    return default_registry.get_tool_schema(name)


def dispatch(name: str, kwargs: dict[str, Any]) -> Any:
    """Convenience wrapper for default_registry.dispatch."""
    return default_registry.dispatch(name, kwargs)
