"""Build public DSDE exports from VMS result objects (no DSDE import)."""

from __future__ import annotations

from typing import Any

from vms.adapters.dsde.contract import DSDEConsumerView, ReturnDistributionExport
from vms.result import ValuationRunResult
from vms.returns.track_b import ReturnDistributionBundleTrackB


def export_return_distribution(bundle: ReturnDistributionBundleTrackB) -> ReturnDistributionExport:
    return ReturnDistributionExport(
        spot_price=bundle.spot_price,
        entry_prices=list(bundle.entry_prices),
        horizons_years=list(bundle.horizons_years),
        mixture=[c.model_dump(mode="json") for c in bundle.mixture],
        compounding_convention=bundle.compounding_convention,
        price_series_convention=bundle.price_series_convention,
        exit_ref=dict(bundle.exit_ref),
        quality_flags=list(bundle.quality_flags),
        investment_value=bundle.investment_value,
        content_fingerprint=bundle.content_fingerprint or None,
        notes=list(bundle.notes) + [
            "Public versioned contract only — no VMS internals.",
            "Not a Kelly / trade instruction. INVESTMENT_VALUE_NOT_ESTABLISHED.",
        ],
    )


def consumer_view_from_result(result: ValuationRunResult) -> DSDEConsumerView:
    """Map a ValuationRunResult to the documented consumer contract (no internals)."""
    req = result.request
    rets = result.returns or {}
    val = result.valuation or {}
    sens = result.sensitivity or {}
    return DSDEConsumerView(
        run_id=result.run_id,
        instrument_id=str(req.get("instrument_id", "")),
        as_of=str(req.get("as_of", "")),
        spot_price=rets.get("spot_price"),
        entry_prices=list(rets.get("entry_prices") or []),
        horizons_years=list(rets.get("horizons_years") or req.get("horizons_years") or []),
        return_mixture=list(rets.get("mixture") or []),
        return_export=None,
        valuation_summary={
            "n_valid_dcf": val.get("n_valid_dcf"),
            "central_vps_dcf": val.get("central_vps_dcf"),
            "aggregates": val.get("aggregates"),
            "terminal_growth": val.get("terminal_growth"),
            "wacc_point": val.get("wacc_point"),
            "flags": val.get("flags"),
        },
        uncertainty_diagnostics={
            "dominant_assumptions": sens.get("dominant_assumptions"),
            "interval_labeling": sens.get("interval_labeling"),
            "content_hash": sens.get("content_hash"),
            "flags": sens.get("flags"),
            "note": "MC percentile bands are not confidence intervals (SENS-MC-PERCENTILE-NOT-CI-v1).",
        },
        regime_posterior=result.regimes,
        market_pricing_ref=rets.get("exit_ref"),
        labels=dict(result.labels),
        investment_value=str(result.labels.get("investment_value", "INVESTMENT_VALUE_NOT_ESTABLISHED")),
        notes=[
            "No legacy PIT/FTD/DV1 imports.",
            "DSDE package not required to build this view.",
            "Do not treat this view as a portfolio Kelly / trade instruction.",
            "PHASE10-DSDE-PUBLIC-CONTRACT-v1",
        ],
    )


def consumer_view_from_track_b(
    *,
    run_id: str,
    instrument_id: str,
    as_of: str,
    bundle: ReturnDistributionBundleTrackB,
    labels: dict[str, Any] | None = None,
) -> DSDEConsumerView:
    export = export_return_distribution(bundle)
    lab = dict(labels or {})
    lab.setdefault("investment_value", "INVESTMENT_VALUE_NOT_ESTABLISHED")
    lab.setdefault("ENGINEERING_PASS", True)
    return DSDEConsumerView(
        run_id=run_id,
        instrument_id=instrument_id,
        as_of=as_of,
        spot_price=bundle.spot_price,
        entry_prices=list(bundle.entry_prices),
        horizons_years=list(bundle.horizons_years),
        return_mixture=[c.model_dump(mode="json") for c in bundle.mixture],
        return_export=export.model_dump(mode="json"),
        valuation_summary={"note": "Track B return export; method-specific valuation is separate."},
        uncertainty_diagnostics={
            "quality_flags": list(bundle.quality_flags),
            "exit_ref": dict(bundle.exit_ref),
            "content_fingerprint": bundle.content_fingerprint,
        },
        regime_posterior=None,
        market_pricing_ref=dict(bundle.exit_ref),
        labels=lab,
        investment_value=str(lab.get("investment_value", "INVESTMENT_VALUE_NOT_ESTABLISHED")),
        notes=list(bundle.notes) + ["PHASE10-DSDE-PUBLIC-CONTRACT-v1"],
    )
