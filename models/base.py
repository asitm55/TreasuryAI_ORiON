"""Shared base model and monetary/ratio decimal type.

ADR-003: all monetary and ratio values use Decimal, never float, to avoid
IEEE 754 rounding error compounding across financial calculations. Pydantic's
default JSON mode serialises Decimal as float, which would silently reintroduce
that error on the wire — ExactDecimal overrides that to serialise as a string.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer

ExactDecimal = Annotated[Decimal, PlainSerializer(lambda v: str(v), return_type=str)]


class TreasuryBaseModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True, str_strip_whitespace=True)
