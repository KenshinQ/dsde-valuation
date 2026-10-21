"""Correlated driver/state path sampling (SPEC §8.2–8.3, VMS-0.2 Phase 3 / SPEC §8.4)."""

from vms.sampling.schemas import (INVALID_REASON_CODES, MATERIAL_BLOCKS, DependenceModel, InvalidPathSummary,
                                  MCDiagnostics, PathRecord, SimulationBundle, YearDrivers)
from vms.sampling.simulate import SAMPLER_VERSION, SamplingGateError, simulate_paths

__all__ = [
    "SAMPLER_VERSION", "SamplingGateError", "INVALID_REASON_CODES", "MATERIAL_BLOCKS",
    "DependenceModel", "InvalidPathSummary", "MCDiagnostics", "PathRecord", "SimulationBundle", "YearDrivers",
    "simulate_paths",
]
