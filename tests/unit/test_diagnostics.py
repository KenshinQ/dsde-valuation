"""Phase 8: OAT isolation, MC≠CI labeling, process vs param, reproducibility, tail sensitivity."""

from __future__ import annotations

import json

import pytest

from tests.company import cyclical_company, loaded_config
from tests.factories import INST
from vms.diagnostics import run_diagnostics
from vms.diagnostics.perturb import driver_means, shock_driver_bundle
from vms.engine import ValuationEngine
from vms.pipeline import run_returns

L = loaded_config()


@pytest.fixture(scope="module")
def baseline():
    load, as_of = cyclical_company()
    # small paths for speed
    run = run_returns(load, instrument_id=INST, as_of=as_of, loaded=L, seed=5, n_paths=25, n_years=3,
                      horizons_years=[1, 3], mode="exploratory", override_reason="test_phase8")
    return load, as_of, run


def test_oat_isolation_only_intended_driver(baseline):
    load, as_of, run = baseline
    assert run.bundle is not None
    base = driver_means(run.bundle)
    shocked, meta = shock_driver_bundle(run.bundle, "revenue_growth", 0.02)
    after = driver_means(shocked)
    assert abs((after["revenue_growth"] - base["revenue_growth"]) - 0.02) < 1e-9
    for k in base:
        if k == "revenue_growth":
            continue
        assert after[k] == pytest.approx(base[k], abs=1e-12)


def test_run_diagnostics_report_structure(baseline):
    load, as_of, run = baseline
    report = run_diagnostics(
        load=load, instrument_id=INST, as_of=as_of, loaded=L, seed=5, n_paths=25, n_years=3,
        baseline=run, mode="exploratory", override_reason="test_phase8")
    assert report.schema_kind == "SensitivityReport"
    assert report.content_hash
    assert any(c.kind == "oat" for c in report.cases)
    assert any(c.kind == "joint" for c in report.cases)
    assert report.process_vs_parameter.get("delta_mean_vps_dcf") is not None
    assert report.dcf_vs_multiple.get("central_vps_dcf") is not None
    assert report.terminal_value_contribution.get("mean_tv_fraction") is not None
    assert report.driver_attribution
    assert report.interval_labeling["rule"] == "MC_PERCENTILE_NOT_CI"
    assert "NOT" in report.interval_labeling["statement"].upper() and "CONFIDENCE INTERVAL" in report.interval_labeling["statement"].upper()
    blob = json.dumps(report.model_dump(mode="json"))
    assert "monte_carlo_percentile_interval" in blob
    assert "not_a_confidence_interval" in blob
    # must not positively claim bands ARE confidence intervals
    assert '"kind": "confidence_interval"' not in blob
    assert '"kind": "statistical_confidence_interval"' not in blob
    # OAT isolation passed
    oat = [c for c in report.cases if c.isolation_check is not None]
    assert oat and all(c.isolation_check["pass"] for c in oat)
    # tail risk
    assert "TAIL_RISK_SENSITIVITY_INCLUDED" in report.flags
    assert report.dominant_assumptions


def test_reproducible_content_hash(baseline):
    load, as_of, run = baseline
    a = run_diagnostics(load=load, instrument_id=INST, as_of=as_of, loaded=L, seed=5, n_paths=25, n_years=3,
                        baseline=run, mode="exploratory", override_reason="test_phase8")
    b = run_diagnostics(load=load, instrument_id=INST, as_of=as_of, loaded=L, seed=5, n_paths=25, n_years=3,
                        baseline=run, mode="exploratory", override_reason="test_phase8")
    assert a.content_hash == b.content_hash


def test_engine_run_diagnostics(baseline):
    load, as_of, run = baseline
    eng = ValuationEngine(L)
    report = eng.run_diagnostics(load, instrument_id=INST, as_of=as_of, seed=5, n_paths=25, n_years=3,
                                 baseline=run, mode="exploratory", override_reason="test_phase8")
    assert report.content_hash


def test_percentile_bands_not_called_ci(baseline):
    load, as_of, run = baseline
    report = run_diagnostics(load=load, instrument_id=INST, as_of=as_of, loaded=L, seed=5, n_paths=25, n_years=3,
                             baseline=run, mode="exploratory", override_reason="test_phase8")
    # valuation metrics on baseline case
    base = next(c for c in report.cases if c.case_id == "baseline")
    band = base.valuation["vps_dcf_mc_percentile_interval_05_95"]
    assert band["kind"] == "monte_carlo_percentile_interval"
    assert band["not_a_confidence_interval"] is True
