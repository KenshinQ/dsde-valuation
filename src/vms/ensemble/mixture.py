"""Distributional mixture P(V)=Σ w_m P_m (SPEC §13.3).

Mixture operates on method-specific sample distributions — never on averaged
point estimates alone (SPEC §22.3). Ineligible methods never enter the mixture
(SPEC §21.2).
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from vms.ensemble.protocols import WeightProtocol
from vms.ensemble.weights import WeightArtifact, WeightValidationError, validate_weight_map
from vms.schemas.contracts import MethodEligibilityStatus, OutputBasis, ValuationTarget

ELIGIBLE_STATUSES = {
    MethodEligibilityStatus.VALID,
    MethodEligibilityStatus.LOW_CONFIDENCE,
}


class MethodDistribution(BaseModel):
    """One method's comparable sample distribution for a declared target/basis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: str
    samples: tuple[float, ...]
    status: MethodEligibilityStatus
    target: ValuationTarget
    output_basis: OutputBasis
    eligible: bool = True
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_samples(self) -> MethodDistribution:
        if self.eligible and not self.samples:
            raise ValueError(f"{self.method_id}: eligible distribution requires samples")
        for x in self.samples:
            if not math.isfinite(float(x)):
                raise ValueError(f"{self.method_id}: non-finite sample")
        return self

    @property
    def median(self) -> float | None:
        if not self.samples:
            return None
        return float(statistics.median(self.samples))

    @property
    def mean(self) -> float | None:
        if not self.samples:
            return None
        return float(statistics.mean(self.samples))


class MixtureDistribution(BaseModel):
    """Weighted mixture of compatible method distributions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    samples: tuple[float, ...]
    weights: dict[str, float]
    protocol: WeightProtocol
    component_method_ids: list[str]
    n_draws: int
    seed: int
    quantiles: dict[str, float] = Field(default_factory=dict)
    mean: float | None = None
    median: float | None = None
    status_label: str = "ENSEMBLE_UNCALIBRATED"
    note: str = ""


def _quantiles(xs: Sequence[float]) -> dict[str, float]:
    if not xs:
        return {}
    arr = np.asarray(xs, dtype=float)
    qs = {
        "p05": float(np.quantile(arr, 0.05)),
        "p25": float(np.quantile(arr, 0.25)),
        "p50": float(np.quantile(arr, 0.50)),
        "p75": float(np.quantile(arr, 0.75)),
        "p95": float(np.quantile(arr, 0.95)),
    }
    return qs


def filter_eligible_components(
    components: Sequence[MethodDistribution],
) -> list[MethodDistribution]:
    """Drop ineligible / empty components. Used before any mixture."""
    out: list[MethodDistribution] = []
    for c in components:
        if not c.eligible:
            continue
        if c.status not in ELIGIBLE_STATUSES:
            continue
        if not c.samples:
            continue
        out.append(c)
    return sorted(out, key=lambda c: c.method_id)


def mix_distributions(
    components: Sequence[MethodDistribution],
    weight_artifact: WeightArtifact,
    *,
    n_draws: int = 2000,
    seed: int = 42,
    status_label: str = "ENSEMBLE_UNCALIBRATED",
    note: str = "",
) -> MixtureDistribution:
    """Draw from Σ w_m P_m by categorical method then uniform sample within method.

    Raises if any weight key is missing from eligible components, if an ineligible
    method appears in weights, or if weight validation fails.
    """
    if n_draws < 1:
        raise WeightValidationError("n_draws must be ≥ 1")
    eligible = filter_eligible_components(components)
    eligible_ids = {c.method_id for c in eligible}
    weights = validate_weight_map(weight_artifact.weights)

    # No ineligible method may contribute (SPEC §21.2)
    for mid in weights:
        if mid not in eligible_ids:
            raise WeightValidationError(
                f"ineligible or missing method '{mid}' cannot enter mixture "
                f"(eligible={sorted(eligible_ids)})"
            )
    # All weight keys must be used; extras among eligible with w=0 are ok only if absent
    by_id = {c.method_id: c for c in eligible}
    ordered_ids = sorted(weights.keys())
    w_arr = np.asarray([weights[m] for m in ordered_ids], dtype=float)
    rng = np.random.default_rng(seed)
    # Pre-materialize per-method sample arrays
    pools = [np.asarray(by_id[m].samples, dtype=float) for m in ordered_ids]
    method_idx = rng.choice(len(ordered_ids), size=n_draws, p=w_arr)
    draws = np.empty(n_draws, dtype=float)
    for i, mi in enumerate(method_idx):
        pool = pools[int(mi)]
        draws[i] = pool[int(rng.integers(0, len(pool)))]
    samples = tuple(float(x) for x in draws.tolist())
    return MixtureDistribution(
        samples=samples,
        weights=dict(weights),
        protocol=weight_artifact.protocol,
        component_method_ids=ordered_ids,
        n_draws=n_draws,
        seed=seed,
        quantiles=_quantiles(samples),
        mean=float(np.mean(draws)),
        median=float(np.median(draws)),
        status_label=status_label,
        note=note or weight_artifact.note,
    )




def diagnostics_with_midcycle_passthrough(
    diagnostics: dict[str, Any] | None,
    source: Any,
) -> dict[str, Any]:
    """Merge source midcycle_estimate into MD diagnostics when present (no invent).

    FI adapters may strip/ignore; this helper never invents a midcycle blob.
    """
    from vms.methods.multiples.midcycle import passthrough_midcycle_diagnostics

    out: dict[str, Any] = dict(diagnostics or {})
    out.update(passthrough_midcycle_diagnostics(source))
    return out


def samples_from_point(
    center: float,
    *,
    n: int = 64,
    relative_spread: float = 0.05,
    seed: int = 0,
) -> tuple[float, ...]:
    """Synthetic local samples around a hand median for offline demos / tests."""
    rng = np.random.default_rng(seed)
    scale = abs(center) * relative_spread if center != 0 else relative_spread
    xs = center + rng.normal(0.0, scale, size=n)
    return tuple(float(x) for x in xs.tolist())


__all__ = [
    "ELIGIBLE_STATUSES",
    "MethodDistribution",
    "MixtureDistribution",
    "filter_eligible_components",
    "mix_distributions",
    "samples_from_point",
    "diagnostics_with_midcycle_passthrough",
]
