"""Annual history extracted from a PIT snapshot (ANNUAL-BASE-v1).

Rules (never invent values):
- Flows: the FY value is the 12-31 record with basis ``cumulative_ytd`` (= full year), or the sum
  of four reported ``standalone_quarter`` records (STANDALONE_QUARTER sources). ``unknown_basis``
  flows give no annual value (flag ANNUAL_BASIS_UNKNOWN).
- Stocks: the 12-31 balance.
- Shares: the last market observation on or before 12-31 of that year (within the year).
- ``not_applicable`` nulls are kept as status ``not_applicable`` (consumers may treat them as 0,
  with a label). ``missing`` nulls stay missing.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from vms.pit.snapshot import PITSnapshot, local_date
from vms.schemas import PRICE_ADJUSTING_ACTIONS
from vms.schemas.fields import REGISTRY


class AnnualPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    value: float | None
    status: str
    ref: str
    formula: str | None = None


class AnnualHistory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instrument_id: str
    years: list[int]
    data: dict[int, dict[str, AnnualPoint]]
    shares: dict[int, AnnualPoint]
    price_adjusting_factor: dict[int, float]   # product of bonus/split ratios with ex_date in that year
    flags: list[str]

    def value(self, year: int, name: str) -> float | None:
        p = self.data.get(year, {}).get(name)
        return None if p is None else p.value

    def point(self, year: int, name: str) -> AnnualPoint | None:
        return self.data.get(year, {}).get(name)


def _ref(r) -> str:  # noqa: ANN001
    return (f"snapshot:{r.source_id}:{r.statement_type}.{r.field_name}@{r.period_end}[{r.basis}]"
            f"#{r.revision_id or '-'}")


def extract_annual(snap: PITSnapshot) -> AnnualHistory:
    flags: set[str] = set()
    data: dict[int, dict[str, AnnualPoint]] = {}
    reported = [f for f in snap.financials if f.formula is None]
    for f in reported:
        cf = REGISTRY.get(f.field_name)
        if cf is None or (f.period_end.month, f.period_end.day) != (12, 31):
            continue
        y = f.period_end.year
        if f.basis in ("balance", "cumulative_ytd"):
            data.setdefault(y, {})[f.field_name] = AnnualPoint(
                value=f.value_cny, status=f.quality_status.value, ref=_ref(f),
                formula=None if f.basis == "balance" else "FY = cumulative YTD at 12-31")
        elif f.basis == "unknown_basis":
            flags.add("ANNUAL_BASIS_UNKNOWN")
    # STANDALONE_QUARTER sources: FY = sum of four quarters
    sq = [f for f in reported if f.basis == "standalone_quarter"]
    keys = {(f.period_end.year, f.field_name) for f in sq}
    for y, name in sorted(keys):
        qs = [f for f in sq if f.period_end.year == y and f.field_name == name]
        if {q.period_end.month for q in qs} == {3, 6, 9, 12} and all(q.value_cny is not None for q in qs):
            data.setdefault(y, {})[name] = AnnualPoint(
                value=sum(q.value_cny for q in qs), status="derived", ref=";".join(_ref(q) for q in qs),
                formula="FY = Q1 + Q2 + Q3 + Q4 (standalone)")
        else:
            flags.add("ANNUAL_INCOMPLETE_QUARTERS")
    years = sorted(y for y, d in data.items() if d.get("revenue") is not None and d["revenue"].value is not None)
    shares: dict[int, AnnualPoint] = {}
    for y in years:
        obs = [m for m in snap.market if m.shares_outstanding is not None and local_date(m.timestamp).year == y
               and local_date(m.timestamp) <= date(y, 12, 31)]
        if obs:
            m = obs[-1]
            shares[y] = AnnualPoint(value=m.shares_outstanding, status="observed",
                                    ref=f"snapshot:market:{m.source_id}@{m.timestamp.isoformat()}")
    factor: dict[int, float] = {}
    for a in snap.corporate_actions:
        e = a.event
        if a.status == "effective" and e.action_type in PRICE_ADJUSTING_ACTIONS:
            factor[e.ex_date.year] = factor.get(e.ex_date.year, 1.0) * e.share_ratio
    return AnnualHistory(instrument_id=snap.instrument_id, years=years, data=data, shares=shares,
                         price_adjusting_factor=factor, flags=sorted(flags))
