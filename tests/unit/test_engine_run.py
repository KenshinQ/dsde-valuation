"""Phase 10: ValuationEngine.run(request, data_bundle, config) → ValuationRunResult."""

from __future__ import annotations

from tests.company import cyclical_company, loaded_config
from tests.factories import INST
from vms import SCHEMA_VERSION, ValuationEngine, ValuationRunResult
from vms.adapters.dsde import consumer_view_from_result, try_notify_dsde
from vms.schemas.observations import ValuationRequest

L = loaded_config()


def test_engine_run_full_pipeline():
    load, as_of = cyclical_company()
    eng = ValuationEngine(L)
    mkt = [m for m in load.market if m.instrument_id == INST]
    spot = float(sorted(mkt, key=lambda x: x.timestamp)[-1].raw_close)
    req = ValuationRequest(
        instrument_id=INST,
        as_of=as_of,
        spot_price=spot,
        horizons_years=[1, 3],
        monte_carlo_paths=40,
        random_seed=42,
        configuration_version=L.config.configuration_version,
    )
    result = eng.run(
        req, load, L, include_sensitivity=False,
        mode="exploratory", override_reason="phase10_unit_engine_run",
    )
    assert isinstance(result, ValuationRunResult)
    assert result.schema_version == SCHEMA_VERSION == "vms-0.2.phase4"
    assert result.run_id.startswith("vms-")
    assert result.labels["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert "ENGINEERING_PASS" in result.labels
    assert result.valuation is not None
    assert result.returns is not None
    assert "SENSITIVITY_SKIPPED" in result.flags

    view = consumer_view_from_result(result)
    assert view.instrument_id == INST
    assert view.return_mixture
    st = try_notify_dsde(view)
    assert st["status"] == "DSDE_ABSENT_NOOP"


def test_engine_run_signature_accepts_none_config():
    load, as_of = cyclical_company()
    eng = ValuationEngine(L)
    mkt = sorted([m for m in load.market if m.instrument_id == INST], key=lambda x: x.timestamp)
    req = ValuationRequest(
        instrument_id=INST, as_of=as_of, spot_price=float(mkt[-1].raw_close),
        horizons_years=[1], monte_carlo_paths=20, random_seed=1,
        configuration_version=L.config.configuration_version,
    )
    result = eng.run(req, load, None, mode="exploratory", override_reason="phase10_none_config")
    assert result.schema_version == SCHEMA_VERSION
