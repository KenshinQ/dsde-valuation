"""Public ValuationEngine facade (SPEC §16.1). Phase-owned methods are live; the rest raise NotImplementedError."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from vms.data.io import LoadResult
from vms.drivers.distributions import DistributionModel
from vms.pipeline import Phase2Run, Phase3Run, Phase4Run, run_estimation, run_projection, run_simulation
from vms.pit.snapshot import PITSnapshot
from vms.quality.report import DataQualityReport, assess
from vms.regimes import RegimeResult
from vms.sampling import SimulationBundle
from vms.schemas.config import LoadedConfig


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

    def project_financials(self, load: LoadResult, *, instrument_id: str, as_of: datetime, **kw: Any) -> Phase2Run:
        return run_projection(load, instrument_id=instrument_id, as_of=as_of, loaded=self.loaded, **kw)

    def value_paths(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("value_paths: Phase 6")

    def build_return_distributions(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("build_return_distributions: Phase 7")

    def run_diagnostics(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("run_diagnostics: Phase 8")

    def run(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("run (end-to-end valuation): Phase 6+")
