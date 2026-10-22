"""EM bank F10 mapper (EM-BANK-F10-v1) — NOTICE-aligned bank lines."""

from __future__ import annotations

from vms.providers.eastmoney.bank_f10 import map_bank_f10_rows
from vms.schemas.fields import REGISTRY


def test_map_bank_f10_fy2024_common_equity_inputs():
    bal = [{
        "REPORT_DATE": "2024-12-31 00:00:00",
        "NOTICE_DATE": "2025-03-15 00:00:00",
        "TOTAL_EQUITY": 494842000000,
        "TOTAL_PARENT_EQUITY": 494842000000,
        "OTHER_EQUITY_TOOL": 69948000000,
        "PREFERRED_SHARES": 19953000000,
        "PERPETUAL_BOND": 49995000000,
        "MINORITY_EQUITY": None,
        "GOODWILL": 7568000000,
    }]
    inc = [{
        "REPORT_DATE": "2024-12-31 00:00:00",
        "NOTICE_DATE": "2025-03-15 00:00:00",
        "BASIC_EPS": 2.15,
        "PARENT_OCI": -374000000,
        "INTEREST_INCOME": 198381000000,
        "INTEREST_NI": 93427000000,
        "PARENT_NETPROFIT": 44508000000,
    }]
    obs, stats = map_bank_f10_rows(
        balance_rows=bal, income_rows=inc, instrument_id="000001.SZ",
    )
    by = {o.field_name: o for o in obs}
    assert "total_equity" not in by  # do not re-emit (avoid HiThink conflict)
    assert "parent_net_income" not in by
    assert by["other_equity_instruments"].value == 69948000000
    assert by["preferred_shares"].value == 19953000000
    assert by["perpetual_bond"].value == 49995000000
    assert by["goodwill"].value == 7568000000
    assert by["basic_eps"].value == 2.15
    assert by["other_comprehensive_income"].value == -374000000
    assert by["interest_income"].value == 198381000000
    assert "minority_interest" not in by  # null not silent-filled
    assert by["basic_eps"].published_at.isoformat().startswith("2025-03-15T15:00:00")
    assert stats["mapped"] >= 7
    for name in (
        "other_equity_instruments", "preferred_shares", "perpetual_bond",
        "basic_eps", "other_comprehensive_income", "interest_income", "goodwill",
    ):
        assert name in REGISTRY


def test_map_skips_interim_when_annual_only():
    bal = [{
        "REPORT_DATE": "2024-06-30 00:00:00",
        "NOTICE_DATE": "2024-08-16 00:00:00",
        "OTHER_EQUITY_TOOL": 1.0,
        "GOODWILL": 1.0,
    }]
    obs, stats = map_bank_f10_rows(balance_rows=bal, instrument_id="000001.SZ", annual_only=True)
    assert obs == []
    assert stats["skipped_non_annual"] >= 1


def test_map_skips_without_notice():
    bal = [{
        "REPORT_DATE": "2024-12-31 00:00:00",
        "NOTICE_DATE": None,
        "OTHER_EQUITY_TOOL": 1.0,
    }]
    obs, stats = map_bank_f10_rows(balance_rows=bal, instrument_id="000001.SZ")
    assert obs == []
    assert stats["skipped_no_notice"] >= 1
