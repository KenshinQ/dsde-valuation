"""Versioned public run result (SPEC §16.1 ValuationRunResult)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vms import SCHEMA_VERSION, __version__
from vms.diagnostics.sensitivity import SensitivityReport
from vms.drivers.distributions import DistributionModel
from vms.quality.report import DataQualityReport
from vms.regimes import RegimeResult
from vms.returns.distributions import ReturnDistributionBundle
from vms.sampling.schemas import SimulationBundle
from vms.schemas.observations import ValuationRequest
from vms.statements.paths import FinancialPathBundle
from vms.evaluation.labels import assign_labels
from vms.valuation.value import ValuationBundle


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ValuationRunResult(_M):
    """Public orchestration result for ValuationEngine.run (SPEC §16.1)."""

    schema_kind: Literal["ValuationRunResult"] = "ValuationRunResult"
    schema_version: str = SCHEMA_VERSION
    package_version: str = __version__
    run_id: str
    request: dict[str, Any]
    quality: dict[str, Any]
    regimes: dict[str, Any] | None = None
    distributions_summary: dict[str, Any] | None = None
    simulation_summary: dict[str, Any] | None = None
    financial_summary: dict[str, Any] | None = None
    valuation: dict[str, Any] | None = None
    returns: dict[str, Any] | None = None
    sensitivity: dict[str, Any] | None = None
    labels: dict[str, Any] = Field(default_factory=dict)
    unsupported_profile: bool = False
    profile_id: str | None = None
    profile_status: str | None = None
    flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @staticmethod
    def build(
        *,
        run_id: str,
        request: ValuationRequest,
        quality: DataQualityReport,
        regimes: RegimeResult | None,
        distributions: DistributionModel | None,
        simulation: SimulationBundle | None,
        financial: FinancialPathBundle | None,
        valuation: ValuationBundle | None,
        returns: ReturnDistributionBundle | None,
        sensitivity: SensitivityReport | None,
        profile_id: str | None,
        profile_status: str | None,
        unsupported: bool,
        flags: list[str] | None = None,
    ) -> "ValuationRunResult":
        eng_ok = (not unsupported) and valuation is not None and returns is not None
        dq_ok = quality.status.value != "BLOCKED" or quality.mode == "exploratory"
        labels = assign_labels(
            engineering_ok=eng_ok,
            data_quality_ok=dq_ok,
            calibration_ok=None,  # Phase 10: calibration assessed on synthetic only → INCONCLUSIVE
            data_label="SYNTHETIC_OR_UNSPECIFIED",
            predeclared_oos_alpha=False,
        )
        labels["calibration_note"] = (
            "Calibration status is SYNTHETIC_ONLY / INCONCLUSIVE for VMS-0.1 release; "
            "no real A-share OOS calibration claim."
        )
        dist_sum = None
        if distributions is not None:
            dist_sum = {
                "n_drivers": len(distributions.drivers),
                "selected_specs": {n: d.selected_spec for n, d in distributions.drivers.items()},
                "seed": distributions.seed,
            }
        sim_sum = None
        if simulation is not None:
            sim_sum = {
                "n_paths": simulation.n_paths,
                "n_valid": simulation.diagnostics.n_paths_valid,
                "n_invalid": simulation.diagnostics.n_paths_invalid,
                "seed": simulation.seed,
                "sampler_version": simulation.sampler_version,
            }
        fin_sum = None
        if financial is not None:
            fin_sum = {
                "n_valid": financial.n_valid,
                "n_failed": financial.n_failed,
                "years": financial.years,
                "policy": financial.policy,
            }
        val_dump = None
        if valuation is not None:
            val_dump = {
                "schema_version": SCHEMA_VERSION,
                "n_valid_dcf": valuation.n_valid_dcf,
                "n_failed": valuation.n_failed,
                "aggregates": valuation.aggregates,
                "terminal_growth": valuation.terminal_growth,
                "wacc_point": valuation.wacc_point.model_dump(mode="json"),
                "central_vps_dcf": (
                    None if not (valuation.central.bridge_dcf and valuation.central.bridge_dcf.valid)
                    else valuation.central.bridge_dcf.value_per_share
                ),
                "flags": valuation.flags,
                "assumptions": valuation.assumptions,
            }
        ret_dump = None
        if returns is not None:
            ret_dump = {
                "schema_version": SCHEMA_VERSION,
                "spot_price": returns.spot_price,
                "entry_prices": returns.entry_prices,
                "horizons_years": returns.horizons_years,
                "n_valid_paths": returns.n_valid_paths,
                "mixture": [c.model_dump(mode="json") for c in returns.mixture],
                "dividend_treatment": returns.dividend_treatment,
                "flags": returns.flags,
                "assumptions": returns.assumptions,
            }
        sens_dump = None
        if sensitivity is not None:
            sens_dump = {
                "schema_version": SCHEMA_VERSION,
                "content_hash": sensitivity.content_hash,
                "dominant_assumptions": sensitivity.dominant_assumptions[:8],
                "interval_labeling": sensitivity.interval_labeling,
                "flags": sensitivity.flags,
            }
        return ValuationRunResult(
            run_id=run_id,
            request=request.model_dump(mode="json"),
            quality={
                "status": quality.status.value,
                "pit_complete": quality.pit_complete,
                "mode": quality.mode,
                "instrument_id": quality.instrument_id,
                "as_of": quality.as_of.isoformat(),
            },
            regimes=None if regimes is None else {
                "states": regimes.current.states,
                "probabilities": regimes.current.probabilities,
                "flags": regimes.current.flags,
            },
            distributions_summary=dist_sum,
            simulation_summary=sim_sum,
            financial_summary=fin_sum,
            valuation=val_dump,
            returns=ret_dump,
            sensitivity=sens_dump,
            labels=labels,
            unsupported_profile=unsupported,
            profile_id=profile_id,
            profile_status=profile_status,
            flags=sorted(set(flags or [])),
            notes=[
                "schema_version stamps all public result types (OUTPUT-CONTRACT-v1).",
                "investment_value defaults to INVESTMENT_VALUE_NOT_ESTABLISHED.",
                "Consumer-facing view: vms.adapters.dsde.consumer_view_from_result",
            ],
        )
