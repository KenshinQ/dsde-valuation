"""Driver definitions: how each historical driver is computed from annual history (SPEC §7.1).

Each definition is a pure function of (history, year) returning (value | None, flags). The
formula string is persisted with every observation for traceability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from vms.drivers.history import AnnualHistory

Result = tuple[float | None, list[str]]


@dataclass(frozen=True)
class DriverDefinition:
    name: str
    formula: str
    inputs: tuple[str, ...]
    fn: Callable[[AnnualHistory, int], Result]


def _v(h: AnnualHistory, y: int, n: str) -> float | None:
    return h.value(y, n)


def _ratio(num: float | None, den: float | None, positive_den: bool = True) -> float | None:
    if num is None or den is None or den == 0 or (positive_den and den < 0):
        return None
    return num / den


def _cogs(h: AnnualHistory, y: int) -> float | None:
    c = _v(h, y, "cost_of_revenue")
    if c is not None:
        return c
    r, g = _v(h, y, "revenue"), _v(h, y, "gross_profit")
    return None if r is None or g is None else r - g


def _gross_margin(h, y) -> Result:  # noqa: ANN001
    r, g = _v(h, y, "revenue"), _v(h, y, "gross_profit")
    if g is None and (c := _v(h, y, "cost_of_revenue")) is not None and r is not None:
        return _ratio(r - c, r), ["GROSS_PROFIT_FROM_COGS"]
    return _ratio(g, r), []


def _ebit_margin(h, y) -> Result:  # noqa: ANN001
    e, r, n = _v(h, y, "ebit"), _v(h, y, "revenue"), _v(h, y, "non_recurring_items_pretax")
    if e is None:
        return None, []
    if n is None:
        return _ratio(e, r), ["ONE_OFFS_NOT_ADJUSTED"]
    return _ratio(e - n, r), ["RECURRING_EBIT"]


def _pretax(h, y) -> float | None:  # noqa: ANN001
    e, i = _v(h, y, "ebit"), _v(h, y, "interest_expense")
    return None if e is None or i is None else e - i


def _tax_rate(h, y) -> Result:  # noqa: ANN001
    pt, t = _pretax(h, y), _v(h, y, "tax_expense")
    if pt is None or t is None or pt <= 0:
        return None, []
    return t / pt, []


def _parent_share(h, y) -> Result:  # noqa: ANN001
    pt, t, p = _pretax(h, y), _v(h, y, "tax_expense"), _v(h, y, "parent_net_income")
    if pt is None or t is None or p is None or pt - t <= 0:
        return None, []
    return p / (pt - t), []


def _growth(h, y) -> Result:  # noqa: ANN001
    r = _ratio(_v(h, y, "revenue"), _v(h, y - 1, "revenue"))
    return (None if r is None else r - 1), []


def _cost_of_debt(h, y) -> Result:  # noqa: ANN001
    i, d, dp = _v(h, y, "interest_expense"), _v(h, y, "interest_bearing_debt"), _v(h, y - 1, "interest_bearing_debt")
    if i is None or d is None:
        return None, []
    avg = (d + dp) / 2 if dp is not None else d
    return (_ratio(i, avg), [] if dp is not None else ["CLOSING_DEBT_ONLY"])


def _share_growth(h, y) -> Result:  # noqa: ANN001
    s, sp = h.shares.get(y), h.shares.get(y - 1)
    if s is None or sp is None or not sp.value:
        return None, []
    f = h.price_adjusting_factor.get(y, 1.0)
    return s.value / sp.value / f - 1, (["BONUS_SPLIT_EXCLUDED"] if f != 1.0 else [])


def _simple(num: str, den: str, positive_num_den: bool = True):  # noqa: ANN202
    def fn(h, y) -> Result:  # noqa: ANN001
        return _ratio(_v(h, y, num), _v(h, y, den), positive_num_den), []
    return fn


def _over_cogs(num: str):  # noqa: ANN202
    def fn(h, y) -> Result:  # noqa: ANN001
        return _ratio(_v(h, y, num), _cogs(h, y)), []
    return fn


def _over_positive_pni(num: str):  # noqa: ANN202
    def fn(h, y) -> Result:  # noqa: ANN001
        p = _v(h, y, "parent_net_income")
        n = _v(h, y, num)
        if p is None or p <= 0 or n is None:
            return None, []
        return n / p, []
    return fn


_D = DriverDefinition
DEFINITIONS: dict[str, DriverDefinition] = {d.name: d for d in [
    _D("revenue_growth", "revenue[y] / revenue[y-1] - 1", ("revenue",), _growth),
    _D("gross_margin", "gross_profit / revenue  (or (revenue - cost_of_revenue) / revenue)",
       ("revenue", "gross_profit", "cost_of_revenue"), _gross_margin),
    _D("ebit_margin", "(ebit - non_recurring_items_pretax) / revenue  (ebit / revenue if one-offs unreported)",
       ("ebit", "revenue", "non_recurring_items_pretax"), _ebit_margin),
    _D("opex_ratio", "operating_expenses / revenue", ("operating_expenses", "revenue"),
       _simple("operating_expenses", "revenue")),
    _D("effective_tax_rate", "tax_expense / (ebit - interest_expense), pre-tax > 0 only",
       ("tax_expense", "ebit", "interest_expense"), _tax_rate),
    _D("parent_share_of_net_income", "parent_net_income / (ebit - interest_expense - tax_expense)",
       ("parent_net_income", "ebit", "interest_expense", "tax_expense"), _parent_share),
    _D("receivables_to_revenue", "accounts_receivable / revenue", ("accounts_receivable", "revenue"),
       _simple("accounts_receivable", "revenue")),
    _D("inventory_to_cogs", "inventory / cost_of_revenue", ("inventory", "cost_of_revenue"), _over_cogs("inventory")),
    _D("payables_to_cogs", "accounts_payable / cost_of_revenue", ("accounts_payable", "cost_of_revenue"),
       _over_cogs("accounts_payable")),
    _D("capex_to_revenue", "capex / revenue", ("capex", "revenue"), _simple("capex", "revenue")),
    _D("da_to_revenue", "depreciation_amortization / revenue", ("depreciation_amortization", "revenue"),
       _simple("depreciation_amortization", "revenue")),
    _D("acquisitions_to_revenue", "acquisitions_net / revenue", ("acquisitions_net", "revenue"),
       _simple("acquisitions_net", "revenue")),
    _D("cost_of_debt", "interest_expense / average(interest_bearing_debt[y], [y-1])",
       ("interest_expense", "interest_bearing_debt"), _cost_of_debt),
    _D("debt_to_revenue", "interest_bearing_debt / revenue", ("interest_bearing_debt", "revenue"),
       _simple("interest_bearing_debt", "revenue")),
    _D("payout_ratio", "dividends_paid / parent_net_income, parent_net_income > 0 (PAYOUT-SAME-YEAR-v1)",
       ("dividends_paid", "parent_net_income"), _over_positive_pni("dividends_paid")),
    _D("repurchases_to_net_income", "share_repurchases / parent_net_income, parent_net_income > 0",
       ("share_repurchases", "parent_net_income"), _over_positive_pni("share_repurchases")),
    _D("diluted_share_growth", "shares[y] / shares[y-1] / bonus_split_ratio[y] - 1", ("shares_outstanding",),
       _share_growth),
    _D("cash_to_revenue", "cash / revenue", ("cash", "revenue"), _simple("cash", "revenue")),
]}
