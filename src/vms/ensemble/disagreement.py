"""Between-method disagreement and leave-one-method-out sensitivity (SPEC §13.5)."""

from __future__ import annotations

import statistics
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from vms.ensemble.mixture import (
    MethodDistribution,
    MixtureDistribution,
    filter_eligible_components,
    mix_distributions,
)
from vms.ensemble.weights import WeightArtifact, equal_prior_weights, validate_weight_map
from vms.schemas.contracts import ValuationTarget


class BetweenMethodDisagreement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    n_methods: int
    method_ids: list[str] = Field(default_factory=list)
    medians_by_method: dict[str, float] = Field(default_factory=dict)
    cross_method_median: float | None = None
    range: float | None = None
    stdev: float | None = None
    mad: float | None = None
    relative_dispersion: float | None = None
    note: str = (
        "dispersion among method medians after normalization; "
        "large disagreement is preserved, not silently averaged (SPEC §13.5)"
    )


class LeaveOneOutCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    left_out: str
    remaining_method_ids: list[str]
    weights: dict[str, float]
    mixture_median: float | None
    mixture_mean: float | None
    delta_median_vs_full: float | None


class LeaveOneOutReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    full_mixture_median: float | None
    full_mixture_mean: float | None
    cases: list[LeaveOneOutCase] = Field(default_factory=list)
    max_abs_delta_median: float | None = None
    note: str = (
        "leave-one-method-out ensemble sensitivity (SPEC §13.5); "
        "method identity preserved"
    )


def between_method_disagreement(
    components: Sequence[MethodDistribution],
) -> BetweenMethodDisagreement:
    eligible = filter_eligible_components(components)
    medians: dict[str, float] = {}
    for c in eligible:
        m = c.median
        if m is not None:
            medians[c.method_id] = m
    ids = sorted(medians.keys())
    if not ids:
        return BetweenMethodDisagreement(n_methods=0)
    xs = [medians[i] for i in ids]
    cross = float(statistics.median(xs))
    rng = float(max(xs) - min(xs))
    stdev = float(statistics.stdev(xs)) if len(xs) >= 2 else 0.0
    mad = float(statistics.median([abs(x - cross) for x in xs]))
    rel = (rng / abs(cross)) if abs(cross) > 1e-12 else None
    return BetweenMethodDisagreement(
        n_methods=len(ids),
        method_ids=ids,
        medians_by_method=medians,
        cross_method_median=cross,
        range=rng,
        stdev=stdev,
        mad=mad,
        relative_dispersion=rel,
    )


def _renormalize_without(
    weights: dict[str, float],
    left_out: str,
) -> dict[str, float] | None:
    remaining = {k: v for k, v in weights.items() if k != left_out}
    if not remaining:
        return None
    total = sum(remaining.values())
    if total <= 0:
        # fall back to equal among remaining
        eq = 1.0 / len(remaining)
        return {k: eq for k in sorted(remaining)}
    return validate_weight_map({k: v / total for k, v in remaining.items()})


def leave_one_method_out(
    components: Sequence[MethodDistribution],
    weight_artifact: WeightArtifact,
    *,
    n_draws: int = 1000,
    seed: int = 42,
    status_label: str = "ENSEMBLE_UNCALIBRATED",
) -> LeaveOneOutReport:
    """Recompute mixture excluding each method in turn (SPEC §13.5)."""
    eligible = filter_eligible_components(components)
    if len(eligible) < 2:
        return LeaveOneOutReport(
            full_mixture_median=None,
            full_mixture_mean=None,
            cases=[],
            note="L1O requires ≥2 eligible methods",
        )

    full = mix_distributions(
        eligible,
        weight_artifact,
        n_draws=n_draws,
        seed=seed,
        status_label=status_label,
        note="full mixture for L1O baseline",
    )
    cases: list[LeaveOneOutCase] = []
    for left in sorted(weight_artifact.weights.keys()):
        rem_w = _renormalize_without(weight_artifact.weights, left)
        if rem_w is None or len(rem_w) < 1:
            continue
        rem_components = [c for c in eligible if c.method_id != left]
        if len(rem_components) < 1:
            continue
        # Build a transient weight artifact with same protocol metadata
        from vms.ensemble.weights import WeightArtifact as WA

        sub_art = WA(
            artifact_kind=weight_artifact.artifact_kind,
            protocol=weight_artifact.protocol,
            weights=rem_w,
            method_ids=sorted(rem_w.keys()),
            calibration_sample_size=weight_artifact.calibration_sample_size,
            oos_evaluated=weight_artifact.oos_evaluated,
            note=f"L1O excluding {left}",
        )
        sub = mix_distributions(
            rem_components,
            sub_art,
            n_draws=n_draws,
            seed=seed + 1,
            status_label=status_label,
            note=f"L1O excluding {left}",
        )
        delta = None
        if full.median is not None and sub.median is not None:
            delta = float(sub.median - full.median)
        cases.append(
            LeaveOneOutCase(
                left_out=left,
                remaining_method_ids=sorted(rem_w.keys()),
                weights=rem_w,
                mixture_median=sub.median,
                mixture_mean=sub.mean,
                delta_median_vs_full=delta,
            )
        )
    deltas = [abs(c.delta_median_vs_full) for c in cases if c.delta_median_vs_full is not None]
    return LeaveOneOutReport(
        full_mixture_median=full.median,
        full_mixture_mean=full.mean,
        cases=cases,
        max_abs_delta_median=max(deltas) if deltas else None,
    )


def prior_equal_l1o_demo(
    components: Sequence[MethodDistribution],
    *,
    target: ValuationTarget,
    n_draws: int = 800,
    seed: int = 42,
) -> tuple[BetweenMethodDisagreement, LeaveOneOutReport, MixtureDistribution]:
    """Convenience for synthetic acceptance: PRIOR_ONLY equal weights + L1O."""
    eligible = filter_eligible_components(components)
    art = equal_prior_weights([c.method_id for c in eligible], target=target)
    disagreement = between_method_disagreement(eligible)
    mixture = mix_distributions(
        eligible,
        art,
        n_draws=n_draws,
        seed=seed,
        status_label="ENSEMBLE_UNCALIBRATED",
        note="PRIOR_ONLY equal-weight research mixture",
    )
    l1o = leave_one_method_out(
        eligible, art, n_draws=n_draws, seed=seed, status_label="ENSEMBLE_UNCALIBRATED",
    )
    return disagreement, l1o, mixture


__all__ = [
    "BetweenMethodDisagreement",
    "LeaveOneOutCase",
    "LeaveOneOutReport",
    "between_method_disagreement",
    "leave_one_method_out",
    "prior_equal_l1o_demo",
]
