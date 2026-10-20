"""Public ValuationEngine facade (SPEC §16.1). Phase 10: full ``run`` → ValuationRunResult."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from vms.data.io import LoadResult
from vms.drivers.distributions import DistributionModel
from vms.pipeline import (Phase2Run, Phase5Run, Phase6Run, Phase7Run, run_estimation, run_path_projection,
                          run_projection, run_returns, run_simulation, run_valuation)
from vms.pit.snapshot import PITSnapshot
from vms.quality.report import DataQualityReport, assess
from vms.regimes import RegimeResult
from vms.reporting.metadata import hash_models, make_run_metadata, sha256_of
from vms.result import ValuationRunResult
from vms.sampling import SimulationBundle
from vms.schemas.config import LoadedConfig
from vms.schemas.observations import ValuationRequest
from vms.statements.paths import FinancialPathBundle, project_financial_paths
from vms.evaluation import EvaluationReport, run_evaluation
from vms.returns import ReturnDistributionBundle, build_return_distributions
from vms.valuation import ValuationBundle, value_paths


class ValuationEngine:
    """Stable facade. ``run`` orchestrates the full pipeline into ValuationRunResult."""

    def __init__(self, loaded: LoadedConfig):
        self.loaded = loaded

    def validate_inputs(self, *args: Any, **kwargs: Any) -> DataQualityReport:
        raise NotImplementedError("validate_inputs facade narrowing: use assess() / vms validate-data (Phase 1)")

    def build_pit_snapshot(self, load: LoadResult, *, instrument_id: str, as_of: datetime,
                           mode: Literal["production", "exploratory"] = "production",
                           override_reason: str | None = None) -> tuple[PITSnapshot, DataQualityReport]:
        return assess(load, instrument_id=instrument_id, as_of=as_of, cfg=self.loaded.config.quality,
                      mode=mode, override_reason=override_reason)

    def estimate_fundamental_state(self, load: LoadResult, *, instrument_id: str, as_of: datetime, seed: int = 0,
                                   mode: Literal["production", "exploratory"] = "production",
                                   override_reason: str | None = None) -> RegimeResult:
        run = run_estimation(load, instrument_id=instrument_id, as_of=as_of, loaded=self.loaded, seed=seed,
                             mode=mode, override_reason=override_reason)
        if run.regimes is None:
            raise RuntimeError("UNSUPPORTED_PROFILE: no fundamental regime")
        return run.regimes

    def estimate_driver_distributions(self, load: LoadResult, *, instrument_id: str, as_of: datetime, seed: int,
                                      mode: Literal["production", "exploratory"] = "production",
                                      override_reason: str | None = None) -> DistributionModel:
        run = run_estimation(load, instrument_id=instrument_id, as_of=as_of, loaded=self.loaded, seed=seed,
                             mode=mode, override_reason=override_reason)
        if run.distributions is None:
            raise RuntimeError("UNSUPPORTED_PROFILE: no driver distributions")
        return run.distributions

    def simulate_paths(self, load: LoadResult, *, instrument_id: str, as_of: datetime, seed: int,
                       n_paths: int | None = None, n_years: int | None = None,
                       mode: Literal["production", "exploratory"] = "production",
                       override_reason: str | None = None) -> SimulationBundle:
        run = run_simulation(load, instrument_id=instrument_id, as_of=as_of, loaded=self.loaded, seed=seed,
                             n_paths=n_paths, n_years=n_years, mode=mode, override_reason=override_reason)
        if run.bundle is None:
            raise RuntimeError("UNSUPPORTED_PROFILE: no simulation")
        return run.bundle

    def project_financials(self, bundle: SimulationBundle, *, snapshot: PITSnapshot, history,
                           drivers, resolution, policy_id: str | None = None) -> FinancialPathBundle:
        """SPEC §16.1: project a SimulationBundle into a FinancialPathBundle."""
        return project_financial_paths(
            bundle=bundle, snapshot=snapshot, history=history, drivers=drivers, resolution=resolution,
            profile=self.loaded.profile, proj_cfg=self.loaded.config.projection,
            ca_cfg=self.loaded.config.capital_allocation, policy_id=policy_id)

    def project_financials_from_load(self, load: LoadResult, *, instrument_id: str, as_of: datetime, seed: int,
                                     n_paths: int | None = None, n_years: int | None = None,
                                     policy_id: str | None = None,
                                     mode: Literal["production", "exploratory"] = "production",
                                     override_reason: str | None = None) -> Phase5Run:
        return run_path_projection(load, instrument_id=instrument_id, as_of=as_of, loaded=self.loaded, seed=seed,
                                   n_paths=n_paths, n_years=n_years, policy_id=policy_id, mode=mode,
                                   override_reason=override_reason)

    def project_central(self, load: LoadResult, *, instrument_id: str, as_of: datetime, **kw: Any) -> Phase2Run:
        return run_projection(load, instrument_id=instrument_id, as_of=as_of, loaded=self.loaded, **kw)

    def value_paths(self, financial: FinancialPathBundle, *, snapshot: PITSnapshot) -> ValuationBundle:
        return value_paths(financial=financial, snapshot=snapshot, loaded=self.loaded)

    def value_from_load(self, load: LoadResult, *, instrument_id: str, as_of: datetime, seed: int,
                        n_paths: int | None = None, n_years: int | None = None, policy_id: str | None = None,
                        mode: Literal["production", "exploratory"] = "production",
                        override_reason: str | None = None) -> Phase6Run:
        return run_valuation(load, instrument_id=instrument_id, as_of=as_of, loaded=self.loaded, seed=seed,
                             n_paths=n_paths, n_years=n_years, policy_id=policy_id, mode=mode,
                             override_reason=override_reason)

    def build_return_distributions(self, valuation: ValuationBundle, financial: FinancialPathBundle, *,
                                     spot_price: float, entry_prices: list[float] | None = None,
                                     horizons_years: list[int] | None = None,
                                     simulation=None, regimes=None) -> ReturnDistributionBundle:
        return build_return_distributions(
            valuation=valuation, financial=financial, loaded=self.loaded, spot_price=spot_price,
            entry_prices=entry_prices, horizons_years=horizons_years, simulation=simulation, regimes=regimes)

    def returns_from_load(self, load: LoadResult, *, instrument_id: str, as_of: datetime, seed: int,
                          spot_price: float | None = None, n_paths: int | None = None,
                          n_years: int | None = None, policy_id: str | None = None,
                          entry_prices: list[float] | None = None, horizons_years: list[int] | None = None,
                          mode: Literal["production", "exploratory"] = "production",
                          override_reason: str | None = None) -> Phase7Run:
        return run_returns(load, instrument_id=instrument_id, as_of=as_of, loaded=self.loaded, seed=seed,
                           spot_price=spot_price, n_paths=n_paths, n_years=n_years, policy_id=policy_id,
                           entry_prices=entry_prices, horizons_years=horizons_years, mode=mode,
                           override_reason=override_reason)

    def run_diagnostics(self, load: LoadResult, *, instrument_id: str, as_of: datetime, seed: int,
                        n_paths: int | None = None, n_years: int | None = None,
                        spot_price: float | None = None, baseline: Phase7Run | None = None,
                        mode: Literal["production", "exploratory"] = "exploratory",
                        override_reason: str | None = "phase8_sensitivity_diagnostics"):
        from vms.diagnostics import run_diagnostics
        return run_diagnostics(
            load=load, instrument_id=instrument_id, as_of=as_of, loaded=self.loaded, seed=seed,
            n_paths=n_paths, n_years=n_years, spot_price=spot_price, baseline=baseline,
            mode=mode, override_reason=override_reason)

    def evaluate(self, *, universe, start, end, out_dir, evaluation_as_of=None,
                 split_mode: str | None = None) -> EvaluationReport:
        """Chronological walk-forward evaluation (Phase 9). Refuses random splits."""
        return run_evaluation(universe=universe, loaded=self.loaded, start=start, end=end, out_dir=out_dir,
                              evaluation_as_of=evaluation_as_of, split_mode=split_mode)

    def run(
        self,
        request: ValuationRequest,
        data_bundle: LoadResult,
        config: LoadedConfig | None = None,
        *,
        include_sensitivity: bool = False,
        sensitivity_paths: int | None = None,
        mode: Literal["production", "exploratory"] = "production",
        override_reason: str | None = None,
        policy_id: str | None = None,
    ) -> ValuationRunResult:
        """Orchestrate validate → estimate → simulate → project → value → returns [(→ sensitivity)].

        SPEC §16.1 signature: ``run(request, data_bundle, config) -> ValuationRunResult``.
        ``config`` defaults to the engine's LoadedConfig. Sensitivity is optional (expensive).
        """
        loaded = config if config is not None else self.loaded
        # Temporarily swap if caller passed a different config (preserve engine state).
        prev = self.loaded
        self.loaded = loaded
        try:
            n_years = max(request.horizons_years)
            p7 = run_returns(
                data_bundle,
                instrument_id=request.instrument_id,
                as_of=request.as_of,
                loaded=loaded,
                seed=request.random_seed,
                spot_price=request.spot_price,
                n_paths=request.monte_carlo_paths,
                n_years=n_years,
                policy_id=policy_id,
                entry_prices=None,
                horizons_years=list(request.horizons_years),
                mode=mode,
                override_reason=override_reason,
            )
            unsupported = (
                p7.resolution is not None
                and getattr(p7.resolution.status, "value", str(p7.resolution.status)) == "UNSUPPORTED_PROFILE"
            ) or (p7.valuation is None and p7.returns is None and p7.distributions is None)
            profile_id = None if p7.resolution is None else p7.resolution.profile_id
            profile_status = None
            if p7.resolution is not None:
                profile_status = getattr(p7.resolution.status, "value", str(p7.resolution.status))

            sensitivity = None
            flags: list[str] = []
            if include_sensitivity and p7.returns is not None and not unsupported:
                from vms.diagnostics import run_diagnostics
                sens_paths = sensitivity_paths if sensitivity_paths is not None else min(
                    50, request.monte_carlo_paths)
                sensitivity = run_diagnostics(
                    load=data_bundle,
                    instrument_id=request.instrument_id,
                    as_of=request.as_of,
                    loaded=loaded,
                    seed=request.random_seed,
                    n_paths=sens_paths,
                    n_years=n_years,
                    spot_price=request.spot_price,
                    baseline=p7,
                    mode="exploratory",
                    override_reason=override_reason or "phase10_engine_run_sensitivity",
                )
                flags.append("SENSITIVITY_INCLUDED")
            else:
                flags.append("SENSITIVITY_SKIPPED")

            data_hash = sha256_of({
                "records": hash_models([
                    *data_bundle.financial, *data_bundle.market, *data_bundle.corporate_actions,
                    *data_bundle.classifications,
                ]),
                "sources": {k: v.model_dump(mode="json") for k, v in sorted(data_bundle.sources.items())},
                "corporate_actions_provided": data_bundle.corporate_actions_provided,
            })
            config_snapshot = {
                "config": loaded.config.model_dump(mode="json"),
                "driver_profile": loaded.profile.model_dump(mode="json"),
            }
            meta = make_run_metadata(
                request=request, config_snapshot=config_snapshot, data_hash=data_hash,
                seed=request.random_seed, paths=request.monte_carlo_paths,
            )

            return ValuationRunResult.build(
                run_id=meta.run_id,
                request=request,
                quality=p7.report,
                regimes=p7.regimes,
                distributions=p7.distributions,
                simulation=p7.bundle,
                financial=p7.financial_paths,
                valuation=p7.valuation,
                returns=p7.returns,
                sensitivity=sensitivity,
                profile_id=profile_id,
                profile_status=profile_status,
                unsupported=bool(unsupported),
                flags=flags,
            )
        finally:
            self.loaded = prev
