"""Traced values: every projected item records its formula and input references.

Reference forms (resolvable by ``unresolved_refs``):
  ``item@year``        another ledger item
  ``driver:<name>``    a DriverModel estimate
  ``policy:<param>``   a capital-allocation policy parameter
  ``config:<param>``   a projection config value
  ``assumption:<id>``  an entry of vms.assumptions.ASSUMPTIONS
  ``snapshot:<ref>``   PIT snapshot provenance (terminal)
  ``corporate_action:<id>`` a known corporate action (terminal)
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict


class TracedValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    value: float
    formula: str
    inputs: list[str]


class Ledger:
    def __init__(self) -> None:
        self.items: dict[str, TracedValue] = {}

    @staticmethod
    def key(item: str, year: int) -> str:
        return f"{item}@{year}"

    def put(self, item: str, year: int, value: float, formula: str, inputs: list[str]) -> float:
        k = self.key(item, year)
        if k in self.items:
            raise KeyError(f"ledger item {k} already set (items are write-once)")
        self.items[k] = TracedValue(value=float(value), formula=formula, inputs=list(inputs))
        return float(value)

    def v(self, item: str, year: int) -> float:
        return self.items[self.key(item, year)].value


def unresolved_refs(items: dict[str, TracedValue], *, drivers: set[str], policy: set[str], config: set[str],
                    assumptions: set[str]) -> list[str]:
    bad = []
    for k, tv in items.items():
        if not tv.formula:
            bad.append(f"{k}: empty formula")
        if not math.isfinite(tv.value):
            bad.append(f"{k}: non-finite")
        for ref in tv.inputs:
            kind, _, name = ref.partition(":")
            ok = {"driver": name in drivers, "policy": name in policy, "config": name in config,
                  "assumption": name in assumptions, "snapshot": bool(name), "corporate_action": bool(name)}.get(
                kind, ref in items)
            if not ok:
                bad.append(f"{k}: unresolved input {ref!r}")
    return bad
