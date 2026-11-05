"""P0/P1 baseline honesty + TSR terminal: no fake incremental edge, no VPS-as-TSR."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from tests.company import company, loaded_config
from vms.evaluation.baselines import build_baselines
from vms.evaluation.labels import assign_labels
from vms.evaluation.metrics import score_targets
from vms.schemas.contracts import ClaimStatus

TZ = ZoneInfo("Asia/Shanghai")
L = loaded_config()


def _spot_from_load(load, as_of: datetime) -> float:
    mkt = [m for m in load.market if m.timestamp <= as_of]
    assert mkt
    return float(mkt[-1].raw_close)


def test_p0_historical_fcff_median_not_equal_forecast_ocf():
    """AC1: historical_median.fcff_y1 is realized-history median, not projected FCFF_y1."""
    # Non-flat CFO path so median of history ≠ projected y1 under growth drivers.
    load, as_of = company(
        years=(2018, 2019, 2020, 2021, 2022),
        growth=0.10,
        overrides={
            (2018, "cash_flow_from_operations"): 80.0,
            (2019, "cash_flow_from_operations"): 90.0,
            (2020, "cash_flow_from_operations"): 200.0,
            (2021, "cash_flow_from_operations"): 110.0,
            (2022, "cash_flow_from_operations"): 120.0,
            (2018, "capex"): 10.0,
            (2019, "capex"): 10.0,
            (2020, "capex"): 10.0,
            (2021, "capex"): 10.0,
            (2022, "capex"): 10.0,
            (2018, "acquisitions_net"): 0.0,
            (2019, "acquisitions_net"): 0.0,
            (2020, "acquisitions_net"): 0.0,
            (2021, "acquisitions_net"): 0.0,
            (2022, "acquisitions_net"): 0.0,
        },
        price=20.0,
    )
    spot = _spot_from_load(load, as_of)
    bundle = build_baselines(
        load=load,
        instrument_id=load.market[0].instrument_id,
        as_of=as_of,
        loaded=L,
        spot=spot,
        horizon_years=1,
    )
    assert "BASELINE_PROJECTION_INVALID" not in bundle["flags"]
    hist = bundle["baselines"]["historical_median"]
    fc_ocf = bundle["forecasts"]["operating_cash_flow"]["point"]
    assert hist["fcff_y1"] is not None
    assert fc_ocf is not None
    assert hist["fcff_y1_n"] >= 3
    assert hist["fcff_y1"] != fc_ocf
    # Realized samples: 70,80,190,100,110 → median 100
    assert hist["fcff_y1"] == pytest.approx(100.0)
    assert "historical_realized" in hist["label"]


def test_p0_forecast_is_baseline_skips_persistence_increment():
    """AC2: FORECAST_IS_BASELINE marked; metrics skip fake vs-persistence edge."""
    load, as_of = company(years=(2019, 2020, 2021, 2022), growth=0.05, price=15.0)
    spot = _spot_from_load(load, as_of)
    iid = load.market[0].instrument_id
    bundle = build_baselines(
        load=load, instrument_id=iid, as_of=as_of, loaded=L, spot=spot, horizon_years=1,
    )
    assert "FORECAST_IS_BASELINE" in bundle["flags"]
    mp = bundle["forecasts"]["market_price"]
    assert mp["forecast_is_baseline"] is True
    assert mp["baseline_source"] == "current_multiple_persistence"
    persist = bundle["baselines"]["current_multiple_persistence"]["exit_price_point"]
    assert mp["point"] == persist

    record = {
        "forecasts": bundle["forecasts"],
        "baselines": bundle["baselines"],
        "flags": bundle["flags"],
        "outcomes": {
            "operating_cash_flow": {"fcff_proxy": 1.0},
            "market_price": {"raw_close": spot},
            "total_shareholder_return": {"realized": 0.1},
            "intrinsic_value": {"later_origin_vps": None},
        },
        "profile_id": "GENERIC",
    }
    scored = score_targets([record])
    vs = scored["market_price"]["vs_current_multiple_persistence"]
    assert vs.get("skipped") is True
    assert vs.get("reason") == "FORECAST_IS_BASELINE"
    assert vs.get("label") == "NO_INFORMATION_GAIN"
    assert "forecast_errors" not in vs
    # mirrored under baseline_comparisons
    vs2 = scored["baseline_comparisons"]["market_price_vs_current_multiple_persistence"]
    assert vs2.get("skipped") is True


def test_p1_tsr_uses_exit_price_not_vps_and_flags_cum_dps_zero():
    """AC3: TSR terminal = persistence exit price; CUM_DPS_ZERO when path DPS is 0."""
    load, as_of = company(years=(2019, 2020, 2021, 2022), growth=0.05, price=15.0)
    spot = _spot_from_load(load, as_of)
    iid = load.market[0].instrument_id
    bundle = build_baselines(
        load=load, instrument_id=iid, as_of=as_of, loaded=L, spot=spot, horizon_years=1,
    )
    tsr = bundle["forecasts"]["total_shareholder_return"]
    exit_px = bundle["baselines"]["current_multiple_persistence"]["exit_price_point"]
    vps = bundle["baselines"]["central_dcf"]["vps"]
    assert exit_px is not None and spot > 0
    assert tsr["terminal_exit_price_proxy"] == exit_px
    assert tsr["terminal_source"] == "current_multiple_persistence"
    assert tsr["terminal_vps_proxy"] is None
    expected = (float(exit_px) + float(tsr["cum_dps"]) - spot) / spot
    assert tsr["point"] == pytest.approx(expected)
    # Must not equal the old VPS-terminal formula when VPS differs from exit price
    if vps is not None and float(vps) != float(exit_px):
        old_vps_ret = (float(vps) + float(tsr["cum_dps"]) - spot) / spot
        assert tsr["point"] != pytest.approx(old_vps_ret)
    if tsr["cum_dps"] == 0.0:
        assert "CUM_DPS_ZERO" in bundle["flags"]
    else:
        # Synthetic company often has projected dividends; force-check flag helper path via metric
        assert "CUM_DPS_ZERO" not in bundle["flags"] or tsr["cum_dps"] == 0.0


def test_p1_cum_dps_zero_flag_when_no_path_dividends(monkeypatch):
    """AC3b: explicitly flag CUM_DPS_ZERO when projected DPS accumulates to 0."""
    from vms.evaluation import baselines as bl

    load, as_of = company(years=(2019, 2020, 2021, 2022), growth=0.05, price=15.0)
    spot = _spot_from_load(load, as_of)
    iid = load.market[0].instrument_id

    real_item = bl._item

    def _item_no_div(proj, name, year, default=None):
        if name == "dividends":
            return 0.0
        return real_item(proj, name, year, default)

    monkeypatch.setattr(bl, "_item", _item_no_div)
    bundle = bl.build_baselines(
        load=load, instrument_id=iid, as_of=as_of, loaded=L, spot=spot, horizon_years=1,
    )
    assert bundle["forecasts"]["total_shareholder_return"]["cum_dps"] == 0.0
    assert "CUM_DPS_ZERO" in bundle["flags"]


def test_fail_closed_labels_unchanged():
    """AC4: PASS / INVESTMENT_VALUE_NOT_ESTABLISHED fail-closed path untouched."""
    lab = assign_labels(
        engineering_ok=True,
        data_quality_ok=True,
        calibration_ok=None,
        data_label="SYNTHETIC",
        n_unbiased_scored=2,
    )
    assert lab["CALIBRATION_CLAIM"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
    assert lab["investment_value"] == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    assert lab.get("ENSEMBLE_CALIBRATED") is not True
