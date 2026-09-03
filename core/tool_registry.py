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
"""

from __future__ import annotations

import inspect
import types
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


def _describe_param(name: str, param: inspect.Parameter) -> dict[str, Any] | None:
    schema = _json_schema_for(param.annotation)
    if schema is None:
        return None
    return schema


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, func: Callable[..., Any], name: str | None = None) -> Callable[..., Any]:
        self._tools[name or func.__name__] = func
        return func

    def list_tools(self) -> list[str]:
        return sorted(self._tools.keys())

    def get_tool_schema(self, name: str) -> dict[str, Any]:
        if name not in self._tools:
            raise ToolNotFoundError(name, self.list_tools())
        func = self._tools[name]
        signature = inspect.signature(func)

        properties: dict[str, Any] = {}
        required: list[str] = []
        for param_name, param in signature.parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            schema = _describe_param(param_name, param)
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
        if name not in self._tools:
            raise ToolNotFoundError(name, self.list_tools())
        return self._tools[name](**kwargs)


default_registry = ToolRegistry()


def tool(func: Callable[..., Any]) -> Callable[..., Any]:
    default_registry.register(func)
    return func


def get_tool_schema(name: str) -> dict[str, Any]:
    return default_registry.get_tool_schema(name)


def dispatch(name: str, kwargs: dict[str, Any]) -> Any:
    return default_registry.dispatch(name, kwargs)
