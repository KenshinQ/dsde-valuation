"""FCFF and FCFE are distinct *types* (SPEC §9.1, §20.8: never mix them).

- ``FCFFSeries`` (unlevered, to all capital providers) may only be discounted with ``WACC``.
- ``FCFESeries`` (levered, to equity) may only be discounted with ``CostOfEquity``.
The two classes share no base class, cannot be combined arithmetically, and cannot be validated
into each other (``kind`` is a literal discriminator). ``present_value`` enforces the pairing at
runtime. The full DCF (terminal value, mid-year conventions, ...) is Phase 6. This module only
provides the type guard and a plain end-of-year PV.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CashFlowTypeError(TypeError):
    pass


class _Series(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    years: list[int]
    values: list[float]

    @model_validator(mode="after")
    def _shape(self):  # noqa: ANN202
        if len(self.years) != len(self.values):
            raise ValueError("years and values must have equal length")
        if any(not math.isfinite(v) for v in self.values):
            raise ValueError("non-finite cash flow")
        return self

    def __add__(self, other):  # noqa: ANN001, ANN204
        raise CashFlowTypeError(f"{type(self).__name__} does not support arithmetic; combine explicitly")

    __radd__ = __sub__ = __rsub__ = __add__


class FCFFSeries(_Series):
    kind: Literal["FCFF"] = "FCFF"
    definition: Literal["NOPAT + D&A - capex - dNWC - acquisitions"] = "NOPAT + D&A - capex - dNWC - acquisitions"


class FCFESeries(_Series):
    kind: Literal["FCFE"] = "FCFE"
    definition: Literal["CFO - capex - acquisitions + net borrowing"] = "CFO - capex - acquisitions + net borrowing"


class _Rate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    rate: float = Field(gt=-1, lt=1)


class WACC(_Rate):
    kind: Literal["WACC"] = "WACC"


class CostOfEquity(_Rate):
    kind: Literal["COST_OF_EQUITY"] = "COST_OF_EQUITY"


_PAIRS = {FCFFSeries: WACC, FCFESeries: CostOfEquity}


def present_value(cf: FCFFSeries | FCFESeries, rate: WACC | CostOfEquity) -> float:
    """End-of-year PV, t = 1..n. Raises CashFlowTypeError on FCFF/FCFE vs rate mismatch."""
    expected = _PAIRS.get(type(cf))
    if expected is None:
        raise CashFlowTypeError(f"unsupported cash-flow type {type(cf).__name__}")
    if type(rate) is not expected:
        raise CashFlowTypeError(f"{type(cf).__name__} must be discounted with {expected.__name__}, "
                                f"got {type(rate).__name__}")
    return sum(v / (1 + rate.rate) ** (i + 1) for i, v in enumerate(cf.values))
