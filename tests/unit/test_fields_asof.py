from datetime import datetime, timedelta, timezone

import pytest

from vms.pit.asof import AS_OF_DATE_RULE, AsOfError, parse_as_of
from vms.schemas.fields import FIELD_REGISTRY_VERSION, FIELDS, REGISTRY


def test_registry_consistency():
    assert FIELD_REGISTRY_VERSION == "FIELDS-1"
    for f in FIELDS:
        assert (f.kind == "stock") == (f.statement_type == "balance_sheet"), f.name
        assert f.unit == "currency"
    # explicit sign conventions requested in the Phase-1 decision
    for name in ("capex", "dividends_paid", "share_repurchases", "cost_of_revenue"):
        assert REGISTRY[name].sign == "positive_magnitude"
    for name in ("ebit", "parent_net_income", "cash_flow_from_operations", "total_equity"):
        assert REGISTRY[name].sign == "signed"


def test_date_only_as_of_is_market_close_shanghai():
    dt, note = parse_as_of("2026-06-30")
    assert dt.isoformat() == "2026-06-30T15:00:00+08:00"
    assert "ASOF-DATE-CLOSE-v1" in note and AS_OF_DATE_RULE["time"] == "15:00:00"


def test_explicit_as_of_kept():
    dt, _ = parse_as_of("2026-06-30T20:00:00+08:00")
    assert dt == datetime(2026, 6, 30, 20, tzinfo=timezone(timedelta(hours=8)))


@pytest.mark.parametrize("bad,needle", [("2026-06-30T15:00:00", "timezone-naive"), ("2026-13-01", "valid"),
                                        ("soon", "ISO-8601")])
def test_bad_as_of(bad, needle):
    with pytest.raises(AsOfError, match=needle):
        parse_as_of(bad)
