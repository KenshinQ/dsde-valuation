"""HiThink field mapper: synthetic HiThink-shaped rows → FinancialObservation."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from vms.providers.hithink.mapping import map_statement_row, mapping_table, ms_to_shanghai_date, notice_to_published_at
from vms.schemas.fields import get_field

TZ = ZoneInfo("Asia/Shanghai")


def _pub(d: date = date(2026, 4, 17)):
    return notice_to_published_at(d)


def test_notice_to_published_at_is_1500_shanghai():
    pub = notice_to_published_at(date(2024, 4, 17))
    assert pub == datetime(2024, 4, 17, 15, 0, tzinfo=TZ)


def test_ms_to_shanghai_date_roundtrip():
    # 2025-12-31 CST midnight-ish from sample period_end
    d = ms_to_shanghai_date(1767110400000)
    assert d == date(2025, 12, 31)


def test_map_income_row_canonical_and_signs():
    row = {
        "period_end_ms": 1767110400000,
        "report_date_ms": 1776355200000,
        "currency": "CNY",
        "operating_income": 1.0e11,
        "operating_costs": -2.0e10,  # wrong sign from vendor → abs
        "operating_profit": 5.0e10,
        "interest_expenses": -1.0e8,
        "income_tax_expense": 1.2e10,
        "parent_holder_net_profit": 3.0e10,
        "operating_expenses": None,
        "sales_fee": 1.0e9,
        "manage_fee": 2.0e9,
        "research_and_development_expenses": 5.0e8,
        "mystery_col": 42.0,
    }
    obs, stats, flags = map_statement_row(
        row, kind="income", instrument_id="600519.SH", published_at=_pub(),
        source_id="hithink_em_notice",
    )
    by = {o.field_name: o for o in obs}
    assert by["revenue"].value == 1.0e11
    assert by["cost_of_revenue"].value == 2.0e10  # abs
    assert by["interest_expense"].value == 1.0e8
    assert by["ebit"].value == 5.0e10
    assert by["parent_net_income"].value == 3.0e10
    assert by["operating_expenses"].value == 1.0e9 + 2.0e9 + 5.0e8
    assert "OPEX_SUM_FEES" in flags
    assert stats.unmapped >= 1
    assert all(o.published_at.hour == 15 for o in obs)
    assert all(o.unit_scale == "unit" for o in obs)
    assert all(o.currency == "CNY" for o in obs)
    assert get_field("revenue").statement_type == by["revenue"].statement_type


def test_map_cashflow_mixed_dividends_low_confidence():
    row = {
        "period_end_ms": 1767110400000,
        "currency": "CNY",
        "act_cash_flow_net": 1.0e10,
        "pay_fixed_assets_etc_cash": 5.0e8,
        "pay_dividends_profits_interest_cash": 2.0e9,
    }
    obs, stats, flags = map_statement_row(
        row, kind="cashflow", instrument_id="600519.SH", published_at=_pub(),
        source_id="hithink_em_notice",
    )
    by = {o.field_name: o for o in obs}
    assert by["capex"].value == 5.0e8
    assert by["dividends_paid"].quality_status.value == "low_confidence"
    assert "DIVIDENDS_PAID_INCLUDES_INTEREST" in flags
    assert stats.mixed_dividend_interest == 1


def test_map_balance_derives_liabilities():
    row = {
        "period_end_ms": 1767110400000,
        "currency": "CNY",
        "cash": 1.0e9,
        "total_debt": 2.0e9,
        "accounts_receivable": 3.0e8,
        "assets_total": 10.0e9,
        "holder_equity_total": 7.0e9,
    }
    obs, stats, flags = map_statement_row(
        row, kind="balance", instrument_id="600519.SH", published_at=_pub(),
        source_id="hithink_em_notice",
    )
    by = {o.field_name: o for o in obs}
    assert by["total_liabilities"].value == 3.0e9
    assert by["total_liabilities"].quality_status.value == "derived"
    assert "TOTAL_LIABILITIES_DERIVED" in flags


def test_mapping_table_documents_rows():
    rows = mapping_table()
    assert any(r["vms_field"] == "revenue" for r in rows)
    assert any(r["vms_field"] == "total_liabilities" for r in rows)
