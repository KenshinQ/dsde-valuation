"""Sector-profile plug-in interface and UNSUPPORTED_PROFILE flagging (SPEC §7.2)."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.company import company, loaded_config
from tests.factories import INST
from vms.drivers.profiles import (ProfileStatus, SectorProfile, get_profile, register_profile, registered_profiles,
                                  resolve_profile)
from vms.pipeline import run_projection
from vms.schemas import InstrumentClassification
from vms.schemas.config import ConfigError, IndustryConfig

CST = timezone(timedelta(hours=8))
IND = loaded_config().config.industry


def cls(ind, scheme="SW2021_L1"):
    return InstrumentClassification(instrument_id=INST, scheme=scheme, industry=ind,
                                    published_at=datetime(2020, 1, 1, tzinfo=CST), source_id="S")


@pytest.mark.parametrize("ind", ["银行", "非银金融"])
def test_financials_unsupported(ind):
    r = resolve_profile(cls(ind), IND)
    assert r.status is ProfileStatus.UNSUPPORTED_PROFILE and r.profile_id is None and "UNSUPPORTED_PROFILE" in r.flags


@pytest.mark.parametrize("ind", ["房地产", "公用事业"])
def test_caution_supported(ind):
    r = resolve_profile(cls(ind), IND)
    assert r.status is ProfileStatus.SUPPORTED and r.flags == ["PROFILE_CAUTION"]


def test_unclassified_and_scheme_mismatch():
    r = resolve_profile(None, IND)
    assert r.status is ProfileStatus.SUPPORTED and r.flags == ["INDUSTRY_UNCLASSIFIED"]
    r = resolve_profile(cls("Banks", scheme="GICS"), IND)
    assert r.status is ProfileStatus.UNSUPPORTED_PROFILE and r.flags == ["INDUSTRY_SCHEME_MISMATCH"]


def test_unsupported_list_is_configurable():
    custom = IND.model_copy(update={"unsupported": ["机械设备"]})
    assert resolve_profile(cls("机械设备"), custom).status is ProfileStatus.UNSUPPORTED_PROFILE
    assert resolve_profile(cls("银行"), custom.model_copy(update={"unsupported": []})).status is ProfileStatus.SUPPORTED


def test_config_errors():
    with pytest.raises(ConfigError, match="not a registered profile"):
        resolve_profile(cls("钢铁"), IND.model_copy(update={"profile_map": {"钢铁": "steel_v9"}}))
    with pytest.raises(ValueError, match="both as unsupported"):
        IndustryConfig(scheme="S", unsupported=["银行"], caution=["银行"])


def test_pipeline_unsupported_profile_no_projection():
    load, as_of = company(industry="银行")
    run = run_projection(load, instrument_id=INST, as_of=as_of, loaded=loaded_config())
    assert run.projection.status == "UNSUPPORTED_PROFILE" and run.drivers is None
    assert run.projection.items == {} and run.projection.fcff is None
    assert run.history.years  # raw metrics are still available


def test_plugin_registration_and_validation():
    assert "operating_company" in registered_profiles()

    @register_profile
    class Dummy(SectorProfile):
        profile_id = "dummy_test_profile"
        required_drivers = frozenset({"revenue_growth", "nonexistent_driver"})

        def project(self, **kw):
            return None

    try:
        prof = loaded_config().profile
        with pytest.raises(ConfigError, match="does not match"):
            get_profile("dummy_test_profile").validate_driver_profile(prof)
        with pytest.raises(ConfigError, match="lacks drivers"):
            get_profile("dummy_test_profile").validate_driver_profile(prof.model_copy(update={"profile_id": "dummy_test_profile"}))
        oc = get_profile("operating_company")
        diag = prof.model_copy(update={"drivers": [d.model_copy(update={"role": "diagnostic"})
                                                   if d.name == "capex_to_revenue" else d for d in prof.drivers]})
        with pytest.raises(ConfigError, match="role=diagnostic"):
            oc.validate_driver_profile(diag)
        with pytest.raises(ValueError, match="already registered"):
            register_profile(Dummy)
    finally:
        from vms.drivers import profiles
        profiles._REGISTRY.pop("dummy_test_profile", None)


def test_no_scattered_sector_conditionals():
    """Industry names must only appear in config / the assumption register, never in code paths."""
    src = Path(__file__).resolve().parents[2] / "src/vms"
    pat = re.compile(r"银行|非银|金融|房地产|公用事业|\bbanks?\b|insurance|real.?estate|utilities", re.I)
    hits = [str(p) for p in src.rglob("*.py") if p.name != "assumptions.py" and pat.search(p.read_text())]
    assert hits == [], hits
