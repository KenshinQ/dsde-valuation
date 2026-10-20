"""Public ValuationEngine facade (SPEC §16.1). Phase-owned methods are live; the rest raise NotImplementedError."""

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
from vms.sampling import SimulationBundle
from vms.schemas.config import LoadedConfig
from vms.statements.paths import FinancialPathBundle, project_financial_paths
from vms.returns import ReturnDistributionBundle, build_return_distributions
from vms.valuation import ValuationBundle, value_paths


class ValuationEngine:
    """Stable facade. Methods for unimplemented phases raise ``NotImplementedError`` with the phase id."""

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

    def run_diagnostics(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("run_diagnostics: Phase 8")

    def run(self, load: LoadResult, *, instrument_id: str, as_of: datetime, seed: int, **kw: Any) -> Phase7Run:
        return self.returns_from_load(load, instrument_id=instrument_id, as_of=as_of, seed=seed, **kw)
