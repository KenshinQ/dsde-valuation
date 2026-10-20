from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from vms.schemas import CorporateActionEvent, SourceDescriptor

CST = timezone(timedelta(hours=8))
BASE = dict(action_id="A1", instrument_id="X", action_type="bonus_share",
            announced_at=datetime(2024, 6, 20, 18, tzinfo=CST), ex_date=date(2024, 7, 10), share_ratio=1.3,
            currency="CNY", source_id="S")


def test_ca_valid():
    assert CorporateActionEvent(**BASE).share_ratio == 1.3


@pytest.mark.parametrize("patch,needle", [
    ({"announced_at": datetime(2024, 6, 20, 18)}, "timezone-naive"),
    ({"ex_date": date(2024, 6, 1)}, "precedes announced_at"),
    ({"share_ratio": None}, "requires share_ratio"),
    ({"share_ratio": 1.0}, "requires share_ratio"),
    ({"action_type": "cash_dividend"}, "requires cash_per_share"),
    ({"action_type": "cash_dividend", "cash_per_share": 0.5}, "must not change shares"),
    ({"action_type": "merger"}, "action_type"),
    ({"currency": "RMB"}, "ISO-4217"),
])
def test_ca_invalid(patch, needle):
    with pytest.raises(ValidationError, match=needle):
        CorporateActionEvent(**{**BASE, **patch})


def test_source_descriptor():
    sd = SourceDescriptor(source_id="S", reporting_convention="CN_CUMULATIVE_YTD", versioning="FULL_HISTORY")
    assert sd.fiscal_year_end == "12-31"
    with pytest.raises(ValidationError, match="reporting_convention"):
        SourceDescriptor(source_id="S", reporting_convention="YTD", versioning="FULL_HISTORY")
    with pytest.raises(ValidationError, match="fiscal_year_end"):
        SourceDescriptor(source_id="S", reporting_convention="UNKNOWN", versioning="UNKNOWN", fiscal_year_end="03-31")
