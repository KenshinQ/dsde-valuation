"""Simulation bundle contracts (SPEC §8.2–8.3, Phase 4)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


INVALID_REASON_CODES = (
    "BOUND_VIOLATION",
    "GROWTH_UNDEFINED",
    "MARGIN_ORDER_UNREPAIRABLE",
    "PARAMETER_DRAW_EMPTY",
    "DEPENDENCE_DRAW_FAILED",
    "NONFINITE_DRAW",
)


MATERIAL_BLOCKS: dict[str, tuple[str, ...]] = {
    "DEMAND_PROFIT": ("revenue_growth", "gross_margin", "ebit_margin", "opex_ratio"),
    "WORKING_CAPITAL": ("receivables_to_revenue", "inventory_to_cogs", "payables_to_cogs"),
    "REINVESTMENT": ("capex_to_revenue", "da_to_revenue", "acquisitions_to_revenue"),
    "CAPITAL": ("debt_to_revenue", "cash_to_revenue", "cost_of_debt", "payout_ratio",
                "repurchases_to_net_income", "diluted_share_growth", "parent_share_of_net_income",
                "effective_tax_rate"),
}


class YearDrivers(_M):
    year_index: int = Field(ge=1)
    state: str
    drivers: dict[str, float]          # raw (bounded) values
    drivers_z: dict[str, float]        # transformed
    flags: list[str] = Field(default_factory=list)


class PathRecord(_M):
    path_id: str
    kind: Literal["central", "monte_carlo"]
    valid: bool
    years: list[YearDrivers]
    parameter_draw_index: dict[str, int | None]   # driver -> bootstrap index (None = point / analytic)
    transition_seed_tag: str
    flags: list[str] = Field(default_factory=list)
    invalid_reason: str | None = None
    assumptions: list[str] = Field(default_factory=list)


class InvalidPathSummary(_M):
    path_id: str
    reason: str
    year_index: int | None = None
    detail: str | None = None


class DependenceModel(_M):
    method: Literal["gaussian_copula_shrunk_pearson"]
    version: str
    drivers: list[str]
    n_overlap_years: int
    prior_strength: float
    shrink_weight_data: float
    correlation: list[list[float]]          # shrunk matrix used for sampling
    correlation_raw: list[list[float]] | None
    regime_overrides: dict[str, list[list[float]]] = Field(default_factory=dict)
    blocks: dict[str, list[str]]
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class MCDiagnostics(_M):
    n_paths_requested: int
    n_paths_valid: int
    n_paths_invalid: int
    invalid_fraction: float
    invalid_by_reason: dict[str, int]
    key_statistics: dict[str, dict[str, float]]   # name -> {mean, std, mcse, p05, p50, p95}
    repeated_seed_max_abs_diff: float | None = None
    repeated_seed_stable: bool | None = None
    flags: list[str] = Field(default_factory=list)


class SimulationBundle(_M):
    sampler_version: str
    schema_kind: Literal["SimulationBundle"] = "SimulationBundle"
    seed: int
    n_paths: int
    n_years: int
    base_year: int
    years: list[int]                       # projection calendar years
    dependence: DependenceModel
    central: PathRecord
    paths: list[PathRecord]                # valid MC paths (may be capped in artifact writer)
    invalid: list[InvalidPathSummary]
    diagnostics: MCDiagnostics
    parameter_snapshot: dict[str, Any]     # hashes + selected specs + regime model ids
    provenance: dict[str, Any]             # data/config/code hashes, stream names
    assumptions: list[str]
    flags: list[str] = Field(default_factory=list)
