"""Canonical financial field vocabulary (SPEC §5.2). Registry version: FIELDS-2 (FIELDS-1 + non_recurring_items_pretax).

Every canonical field declares:
- statement_type: income | cash_flow | balance_sheet
- kind: ``flow`` (accumulates over a period; eligible for cumulative→standalone conversion)
        or ``stock`` (point-in-time balance; NEVER converted)
- unit: ``currency`` (all Phase-1 fields are currency amounts, normalised to CNY yuan)
- sign: ``positive_magnitude`` (stored as a non-negative magnitude even when economically an
        outflow/expense — e.g. capex = 100 means 100 of cash spent), ``nonnegative`` (cannot be
        negative by nature), or ``signed`` (either sign meaningful, convention in description).

Sign conventions are enforced by the quality gate: a negative value in a positive_magnitude /
nonnegative field is a CRITICAL error (it usually means a provider used the opposite convention,
and silently flipping it would risk double-negation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FIELD_REGISTRY_VERSION = "FIELDS-2"

Kind = Literal["flow", "stock"]
Sign = Literal["positive_magnitude", "nonnegative", "signed"]


@dataclass(frozen=True)
class CanonicalField:
    name: str
    statement_type: Literal["income", "cash_flow", "balance_sheet"]
    kind: Kind
    sign: Sign
    description: str
    unit: Literal["currency"] = "currency"


_F = CanonicalField
FIELDS: tuple[CanonicalField, ...] = (
    # ---- income statement (flows)
    _F("revenue", "income", "flow", "nonnegative", "Operating revenue (营业收入)"),
    _F("cost_of_revenue", "income", "flow", "positive_magnitude", "Cost of revenue (营业成本), stored positive"),
    _F("gross_profit", "income", "flow", "signed", "Revenue - cost of revenue; negative = gross loss"),
    _F("operating_expenses", "income", "flow", "positive_magnitude",
       "Selling + G&A + R&D (+ taxes & surcharges if provider includes), stored positive"),
    _F("ebit", "income", "flow", "signed", "Operating profit before interest and tax; negative = loss"),
    _F("interest_expense", "income", "flow", "positive_magnitude", "Gross interest expense, stored positive"),
    _F("tax_expense", "income", "flow", "signed", "Income tax expense; negative = tax benefit"),
    _F("parent_net_income", "income", "flow", "signed", "Net income attributable to parent (归母净利润)"),
    _F("depreciation_amortization", "income", "flow", "positive_magnitude", "D&A, stored positive"),
    _F("non_recurring_items_pretax", "income", "flow", "signed",
       "Pre-tax non-recurring items included in EBIT (非经常性损益, pre-tax); positive = gain"),
    # ---- cash flow statement (flows)
    _F("cash_flow_from_operations", "cash_flow", "flow", "signed", "Net CFO; negative = net operating outflow"),
    _F("capex", "cash_flow", "flow", "positive_magnitude",
       "Purchases of PP&E/intangibles, stored as positive outflow magnitude"),
    _F("acquisitions_net", "cash_flow", "flow", "signed",
       "Acquisitions net of disposals; positive = net cash OUTflow"),
    _F("dividends_paid", "cash_flow", "flow", "positive_magnitude", "Cash dividends paid, positive magnitude"),
    _F("share_repurchases", "cash_flow", "flow", "positive_magnitude", "Cash spent on buybacks, positive magnitude"),
    _F("share_issuance_proceeds", "cash_flow", "flow", "positive_magnitude", "Cash from equity issuance, positive"),
    _F("debt_issuance", "cash_flow", "flow", "positive_magnitude", "Cash from new borrowings, positive"),
    _F("debt_repayment", "cash_flow", "flow", "positive_magnitude", "Cash used to repay borrowings, positive"),
    # ---- balance sheet (stocks)
    _F("cash", "balance_sheet", "stock", "nonnegative", "Cash and equivalents"),
    _F("interest_bearing_debt", "balance_sheet", "stock", "nonnegative", "Short + long-term borrowings + bonds"),
    _F("accounts_receivable", "balance_sheet", "stock", "nonnegative", "Trade receivables (incl. notes)"),
    _F("inventory", "balance_sheet", "stock", "nonnegative", "Inventories"),
    _F("accounts_payable", "balance_sheet", "stock", "nonnegative", "Trade payables (incl. notes)"),
    _F("contract_assets", "balance_sheet", "stock", "nonnegative", "Contract assets"),
    _F("contract_liabilities", "balance_sheet", "stock", "nonnegative", "Contract liabilities / advances"),
    _F("goodwill", "balance_sheet", "stock", "nonnegative", "Goodwill"),
    _F("intangible_assets", "balance_sheet", "stock", "nonnegative", "Intangible assets"),
    _F("minority_interest", "balance_sheet", "stock", "signed", "Non-controlling interests (can be negative)"),
    _F("total_assets", "balance_sheet", "stock", "nonnegative", "Total assets"),
    _F("total_liabilities", "balance_sheet", "stock", "nonnegative", "Total liabilities"),
    _F("total_equity", "balance_sheet", "stock", "signed",
       "Total equity INCLUDING minority interest; identity: total_assets = total_liabilities + total_equity"),
    _F("parent_equity", "balance_sheet", "stock", "signed", "Equity attributable to parent"),
)

REGISTRY: dict[str, CanonicalField] = {f.name: f for f in FIELDS}
assert len(REGISTRY) == len(FIELDS), "duplicate canonical field"


def get_field(name: str) -> CanonicalField | None:
    return REGISTRY.get(name)
