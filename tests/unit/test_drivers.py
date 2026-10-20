"""Driver definitions, transforms, history extraction and central estimates (Phase 2)."""

import math

import pytest

from tests.company import company, loaded_config
from tests.factories import INST, fobs, mobs, src
from tests.conftest import make_load
from vms.drivers.definitions import DEFINITIONS
from vms.drivers.estimate import DriverEstimationError, estimate_drivers
from vms.drivers.history import extract_annual
from vms.drivers.transforms import forward, inverse
from vms.quality.report import assess


def hist(load, as_of):
    snap, _ = assess(load, instrument_id=INST, as_of=as_of, cfg=loaded_config().config.quality)
    return extract_annual(snap)


def test_definitions_match_profile():
    prof = loaded_config().profile
    assert {d.name for d in prof.drivers} == set(DEFINITIONS)
    for d in DEFINITIONS.values():
        assert d.formula and d.inputs


@pytest.mark.parametrize("t,lo,hi,x", [("identity", -1, 1, 0.3), ("log1p", -0.8, 3, 0.25), ("logit", 0, 0.5, 0.2)])
def test_transform_round_trip(t, lo, hi, x):
    assert inverse(t, forward(t, x, lo, hi), lo, hi) == pytest.approx(x)


def test_history_and_core_driver_values():
    h = hist(*company(growth=0.10))
    assert h.years == [2021, 2022, 2023, 2024]
    g, _ = DEFINITIONS["revenue_growth"].fn(h, 2024)
    assert g == pytest.approx(0.10)
    assert DEFINITIONS["gross_margin"].fn(h, 2024)[0] == pytest.approx(0.30)
    assert DEFINITIONS["effective_tax_rate"].fn(h, 2024)[0] == pytest.approx(24 / 96)
    assert DEFINITIONS["inventory_to_cogs"].fn(h, 2024)[0] == pytest.approx(120 / 700)


def test_ebit_margin_one_off_handling():
    load, as_of = company(overrides={(2024, "ebit"): 130.0})
    h = hist(load, as_of)
    v, flags = DEFINITIONS["ebit_margin"].fn(h, 2024)
    assert flags == ["ONE_OFFS_NOT_ADJUSTED"]
    load.financial.append(fobs("2024-12-31", "non_recurring_items_pretax", 30.0, "2025-04-20"))
    h = hist(load, as_of)
    v, flags = DEFINITIONS["ebit_margin"].fn(h, 2024)
    assert flags == ["RECURRING_EBIT"] and v == pytest.approx(100.0 / (1000 * 1.05 ** 3))


def test_tax_rate_and_payout_skip_loss_years():
    load, as_of = company(overrides={(2024, "ebit"): -50.0, (2024, "parent_net_income"): -40.0})
    h = hist(load, as_of)
    assert DEFINITIONS["effective_tax_rate"].fn(h, 2024)[0] is None
    assert DEFINITIONS["payout_ratio"].fn(h, 2024)[0] is None


def test_share_growth_excludes_bonus_shares():
    from tests.factories import ca
    load, as_of = company(shares=(1e3, 1e3, 1.3e3, 1.3e3 * 1.02),
                          actions=[ca("B", "bonus_share", "2023-04-20", "2023-06-10", ratio=1.3)])
    h = hist(load, as_of)
    v, flags = DEFINITIONS["diluted_share_growth"].fn(h, 2023)
    assert v == pytest.approx(0.0) and flags == ["BONUS_SPLIT_EXCLUDED"]
    assert DEFINITIONS["diluted_share_growth"].fn(h, 2024)[0] == pytest.approx(0.02)


def test_unknown_basis_gives_no_annual_values():
    load, as_of = company()
    load.sources = {}
    h = hist(load, as_of)
    assert "ANNUAL_BASIS_UNKNOWN" in h.flags and h.years == []


def test_standalone_quarters_summed():
    fin = [fobs(f"2024-{m:02d}-{d}", "revenue", 100.0, f"2025-04-20") for m, d in ((3, 31), (6, 30), (9, 30), (12, 31))]
    load = make_load(fin, [mobs("2025-04-30", 10)], sources=[src("STANDALONE_QUARTER")])
    h = hist(load, fin[0].published_at.replace(month=5))
    assert h.value(2024, "revenue") == 400.0 and h.point(2024, "revenue").formula.startswith("FY = Q1")


def test_estimates_median_flags_and_fallback():
    cfgp = loaded_config()
    h = hist(*company(growth=0.05))
    dm = estimate_drivers(h, cfgp.profile, cfgp.config.projection)
    e = dm.estimates["revenue_growth"]
    assert e.method == "historical_median" and e.n_obs == 3 and e.value == pytest.approx(0.05)
    assert e.observations[0].year == 2022 and math.isfinite(e.transformed_value)
    # acquisitions_net present as 0 -> historical 0; drop field entirely -> prior fallback + low confidence
    load, as_of = company(drop={(y, "share_repurchases") for y in range(2021, 2025)})
    dm = estimate_drivers(hist(load, as_of), cfgp.profile, cfgp.config.projection)
    r = dm.estimates["repurchases_to_net_income"]
    assert r.method == "prior_fallback" and r.low_confidence and "PRIOR_FALLBACK" in r.flags


def test_clipping_flagged():
    cfgp = loaded_config()
    load, as_of = company(overrides={(y, "capex"): 5000.0 for y in range(2021, 2025)})
    dm = estimate_drivers(hist(load, as_of), cfgp.profile, cfgp.config.projection)
    e = dm.estimates["capex_to_revenue"]
    assert e.clipped and e.value == e.upper and {"CLIPPED_TO_BOUND", "OBS_OUT_OF_BOUNDS"} <= set(e.flags)


def test_low_confidence_short_history():
    cfgp = loaded_config()
    dm = estimate_drivers(hist(*company(years=(2023, 2024), shares=(1e3, 1e3))), cfgp.profile,
                          cfgp.config.projection)
    assert dm.estimates["revenue_growth"].n_obs == 1 and dm.estimates["revenue_growth"].low_confidence


def test_unknown_driver_and_missing_prior_errors():
    cfgp = loaded_config()
    h = hist(*company())
    bad = cfgp.profile.model_copy(update={"drivers": [*cfgp.profile.drivers,
                                                      cfgp.profile.drivers[0].model_copy(update={"name": "magic"})]})
    with pytest.raises(DriverEstimationError, match="no definition"):
        estimate_drivers(h, bad, cfgp.config.projection)
    noprior = cfgp.profile.model_copy(update={"drivers": [d.model_copy(update={"prior": None})
                                                          if d.name == "repurchases_to_net_income" else d
                                                          for d in cfgp.profile.drivers]})
    load, as_of = company(drop={(y, "share_repurchases") for y in range(2021, 2025)})
    with pytest.raises(DriverEstimationError, match="no history and no prior"):
        estimate_drivers(hist(load, as_of), noprior, cfgp.config.projection)
