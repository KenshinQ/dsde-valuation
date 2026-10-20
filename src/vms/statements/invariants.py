"""Accounting invariants (SPEC §9.2). Recomputed independently from ledger values.

A projection that violates any invariant is REJECTED with reason codes. It is never repaired.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from vms.statements.ledger import TracedValue

REASON_CODES = {
    "NON_FINITE": "a projected value is NaN/Inf",
    "CASH_RECONCILIATION_FAIL": "cash change != CFO - capex - acquisitions + net borrowing - dividends - repurchases + issuance",
    "DEBT_ROLLFORWARD_FAIL": "debt != opening + issuance + revolver - repayment",
    "NEGATIVE_DEBT": "debt below zero",
    "EQUITY_ROLLFORWARD_FAIL": "equity != opening + net income - distributions + issuance",
    "DISTRIBUTION_DOUBLE_COUNT": "distributions_to_shareholders != dividends + repurchases",
    "BALANCE_SHEET_FAIL": "assets - liabilities - equity != base-year residual",
    "NWC_LINK_FAIL": "operating NWC / change in NWC inconsistent with balances",
    "INCOME_LINK_FAIL": "net income != EBIT - interest + interest income - tax, or gross profit/COGS inconsistent",
    "FCFF_COMPOSITION_FAIL": "FCFF != NOPAT + D&A - capex - dNWC - acquisitions",
    "FCFE_COMPOSITION_FAIL": "FCFE != CFO - capex - acquisitions + net borrowing",
    "FCF_BRIDGE_FAIL": "FCFF - FCFE != interest - interest income + book tax - operating tax - net borrowing",
    "DIVIDEND_TIMING_FAIL": "dividends paid in y != dividends declared on FY y-1 (DIVIDEND-T-PLUS-1-v1)",
    "REVOLVER_EXCEEDS_DEBT": "revolver balance negative or above total debt",
    "NEGATIVE_TAX": "tax expense or operating tax below zero",
    "REPURCHASE_INCONSISTENT": "repurchase cash != shares repurchased x price",
    "ISSUANCE_INCONSISTENT": "issuance cash != shares issued x price",
    "SHARES_ROLLFORWARD_FAIL": "shares != opening x pending ratio + dilution - repurchased + issued",
    "NONPOSITIVE_SHARES": "shares outstanding <= 0",
    "BELOW_MIN_CASH": "cash below the revolver floor",
}


class Violation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    year: int
    detail: str


def check_invariants(items: dict[str, TracedValue], base_year: int, years: list[int], *, tol: float,
                     min_cash_to_revenue: float) -> list[Violation]:
    out: list[Violation] = []

    def v(name: str, y: int) -> float:
        return items[f"{name}@{y}"].value

    def bad(code: str, y: int, lhs: float, rhs: float) -> None:
        scale = max(1.0, abs(lhs), abs(rhs))
        if not math.isclose(lhs, rhs, rel_tol=1e-9, abs_tol=tol) and abs(lhs - rhs) > 1e-9 * scale + tol:
            out.append(Violation(code=code, year=y, detail=f"{lhs:.6g} != {rhs:.6g}"))

    for k, tv in items.items():
        if not math.isfinite(tv.value):
            out.append(Violation(code="NON_FINITE", year=int(k.rsplit("@", 1)[1]), detail=k))
    if out:
        return out
    residual = v("total_assets", base_year) - v("total_liabilities", base_year) - v("total_equity", base_year)
    for y in years:
        p = y - 1
        cfo, capex, acq = v("cash_flow_from_operations", y), v("capex", y), v("acquisitions", y)
        div, rep, iss = v("dividends", y), v("share_repurchases", y), v("share_issuance_proceeds", y)
        nb = v("net_borrowing", y)
        bad("CASH_RECONCILIATION_FAIL", y, v("cash", y) - v("cash", p), cfo - capex - acq + nb - div - rep + iss)
        bad("DEBT_ROLLFORWARD_FAIL", y, v("interest_bearing_debt", y),
            v("interest_bearing_debt", p) + v("debt_issuance", y) + v("revolver_draw", y) - v("debt_repayment", y))
        bad("DEBT_ROLLFORWARD_FAIL", y, nb, v("debt_issuance", y) + v("revolver_draw", y) - v("debt_repayment", y))
        if v("interest_bearing_debt", y) < -tol:
            out.append(Violation(code="NEGATIVE_DEBT", year=y, detail=str(v("interest_bearing_debt", y))))
        bad("DISTRIBUTION_DOUBLE_COUNT", y, v("distributions_to_shareholders", y), div + rep)
        bad("EQUITY_ROLLFORWARD_FAIL", y, v("total_equity", y),
            v("total_equity", p) + v("net_income", y) - v("distributions_to_shareholders", y) + iss)
        bad("BALANCE_SHEET_FAIL", y, v("total_assets", y) - v("total_liabilities", y) - v("total_equity", y), residual)
        onwc = v("accounts_receivable", y) + v("inventory", y) - v("accounts_payable", y)
        bad("NWC_LINK_FAIL", y, v("operating_nwc", y), onwc)
        bad("NWC_LINK_FAIL", y, v("delta_operating_nwc", y), v("operating_nwc", y) - v("operating_nwc", p))
        bad("INCOME_LINK_FAIL", y, v("net_income", y),
            v("ebit", y) - v("interest_expense", y) + v("interest_income", y) - v("tax_expense", y))
        bad("DIVIDEND_TIMING_FAIL", y, div, v("dividends_declared", p))
        if not (-tol <= v("revolver_balance", y) <= v("interest_bearing_debt", y) + tol):
            out.append(Violation(code="REVOLVER_EXCEEDS_DEBT", year=y, detail=str(v("revolver_balance", y))))
        bad("INCOME_LINK_FAIL", y, v("gross_profit", y), v("revenue", y) - v("cost_of_revenue", y))
        bad("FCFF_COMPOSITION_FAIL", y, v("fcff", y),
            v("nopat", y) + v("depreciation_amortization", y) - capex - v("delta_operating_nwc", y) - acq)
        bad("FCFE_COMPOSITION_FAIL", y, v("fcfe", y), cfo - capex - acq + nb)
        bad("FCF_BRIDGE_FAIL", y, v("fcff", y) - v("fcfe", y),
            v("interest_expense", y) - v("interest_income", y) + v("tax_expense", y) - v("operating_tax", y) - nb)
        if v("tax_expense", y) < -tol or v("operating_tax", y) < -tol:
            out.append(Violation(code="NEGATIVE_TAX", year=y, detail="tax < 0"))
        price = v("transaction_price", y)
        bad("REPURCHASE_INCONSISTENT", y, rep, v("shares_repurchased", y) * price)
        bad("ISSUANCE_INCONSISTENT", y, iss, v("shares_issued", y) * price)
        sh_tol = 1e-6 * max(1.0, v("shares_outstanding", p))
        exp_sh = (v("shares_outstanding", p) * v("pending_share_ratio", y) + v("shares_dilution", y)
                  - v("shares_repurchased", y) + v("shares_issued", y))
        if abs(v("shares_outstanding", y) - exp_sh) > sh_tol:
            out.append(Violation(code="SHARES_ROLLFORWARD_FAIL", year=y, detail=f"{v('shares_outstanding', y)} != {exp_sh}"))
        if v("shares_outstanding", y) <= 0:
            out.append(Violation(code="NONPOSITIVE_SHARES", year=y, detail=str(v("shares_outstanding", y))))
        if v("cash", y) < min_cash_to_revenue * v("revenue", y) - tol:
            out.append(Violation(code="BELOW_MIN_CASH", year=y, detail=f"cash {v('cash', y):.6g}"))
    return out
