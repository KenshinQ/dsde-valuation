"""Method comparison, normalization and disagreement (SPEC §13.1 / §13.5).

Phase 7: normalize only when mathematically valid; preserve method identity;
report disagreement. Mixture combination is delegated to vms.ensemble (Phase 8).
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.methods.protocol import MethodResult
from vms.router.compatibility import (
    CompatibilityReport,
    check_combination_compatibility,
    refuse_uncalibrated_blend,
)
from vms.schemas.contracts import (
    ClaimStatus,
    MethodEligibilityStatus,
    OutputBasis,
    ValuationTarget,
)


def _extract_point(raw: Any) -> float | None:
    """Pull a comparable scalar from agg dict ({p50/mean/...}) or bare float."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and math.isfinite(float(raw)):
        return float(raw)
    if isinstance(raw, dict):
        for key in ("p50", "median", "mean", "value"):
            v = raw.get(key)
            if isinstance(v, (int, float)) and math.isfinite(float(v)):
                return float(v)
    return None


def extract_basis_scalar(result: MethodResult, basis: OutputBasis) -> float | None:
    vals = result.values or {}
    if basis is OutputBasis.EQUITY:
        return (
            _extract_point(vals.get("equity_value"))
            or _extract_point(vals.get("nav_equity"))
            or _extract_point(vals.get("nav"))
        )
    if basis is OutputBasis.EV:
        return _extract_point(vals.get("enterprise_value"))
    if basis is OutputBasis.NAV:
        return (
            _extract_point(vals.get("nav"))
            or _extract_point(vals.get("nav_equity"))
            or _extract_point(vals.get("equity_value"))
        )
    if basis is OutputBasis.PER_SHARE:
        return _extract_point(vals.get("value_per_share"))
    if basis is OutputBasis.MARKET_PRICE:
        return _extract_point(vals.get("market_price")) or _extract_point(vals.get("exit_price"))
    return None


class NormalizedMethodValue(BaseModel):
    """Normalized scalar that still carries method identity (SPEC §13.5)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: str
    status: MethodEligibilityStatus
    output_basis: OutputBasis
    target: ValuationTarget
    horizon: int | None = None
    value: float
    source_field: str
    normalization: str = "identity_extract"
    retained_identity: bool = True


class DisagreementReport(BaseModel):
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


class MethodComparisonReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target: ValuationTarget
    horizon: int | None
    requested_output_basis: OutputBasis
    method_results_retained: list[str] = Field(default_factory=list)
    normalized: list[NormalizedMethodValue] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)
    disagreement: DisagreementReport
    compatibility: CompatibilityReport
    ensemble: dict[str, Any] = Field(default_factory=dict)
    investment_value: str = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    notes: str = ""


def normalize_method_result(
    result: MethodResult,
    *,
    target: ValuationTarget,
    horizon: int | None,
    requested_output_basis: OutputBasis,
) -> tuple[NormalizedMethodValue | None, str | None]:
    """Normalize one method result when mathematically valid; keep method_id."""
    if result.status not in {
        MethodEligibilityStatus.VALID,
        MethodEligibilityStatus.LOW_CONFIDENCE,
    }:
        return None, f"status={result.status.value}"
    if not result.values:
        return None, "empty_values"

    # Map requested basis → preferred source field name for provenance
    field_map = {
        OutputBasis.EQUITY: ("equity_value", "nav_equity", "nav"),
        OutputBasis.EV: ("enterprise_value",),
        OutputBasis.NAV: ("nav", "nav_equity", "equity_value"),
        OutputBasis.PER_SHARE: ("value_per_share",),
        OutputBasis.MARKET_PRICE: ("market_price", "exit_price"),
    }
    vals = result.values or {}
    source = None
    value = None
    for fname in field_map[requested_output_basis]:
        value = _extract_point(vals.get(fname))
        if value is not None:
            source = fname
            break

    if value is None:
        # EV method without equity bridge cannot normalize to EQUITY
        if (
            requested_output_basis is OutputBasis.EQUITY
            and OutputBasis.EV in set(result.output_basis or [])
            and "equity_value" not in vals
        ):
            return None, "EV_EQUITY_BRIDGE_REQUIRED"
        return None, f"no_scalar_for_basis={requested_output_basis.value}"

    # Unit conversion beyond identity extract is out of Phase 7 scope
    return (
        NormalizedMethodValue(
            method_id=result.method_id,
            status=result.status,
            output_basis=requested_output_basis,
            target=target,
            horizon=horizon,
            value=value,
            source_field=source or "unknown",
            normalization="identity_extract",
            retained_identity=True,
        ),
        None,
    )


def _disagreement(normalized: list[NormalizedMethodValue]) -> DisagreementReport:
    medians = {n.method_id: n.value for n in normalized}
    ids = [n.method_id for n in normalized]
    if not normalized:
        return DisagreementReport(n_methods=0, method_ids=[], medians_by_method={})
    xs = [n.value for n in normalized]
    cross = float(statistics.median(xs))
    rng = float(max(xs) - min(xs))
    stdev = float(statistics.stdev(xs)) if len(xs) >= 2 else 0.0
    mad = float(statistics.median([abs(x - cross) for x in xs]))
    rel = (rng / abs(cross)) if abs(cross) > 1e-12 else None
    return DisagreementReport(
        n_methods=len(normalized),
        method_ids=ids,
        medians_by_method=medians,
        cross_method_median=cross,
        range=rng,
        stdev=stdev,
        mad=mad,
        relative_dispersion=rel,
    )


def compare_methods(
    results: list[MethodResult],
    *,
    target: ValuationTarget,
    horizon: int | None = None,
    requested_output_basis: OutputBasis = OutputBasis.EQUITY,
    result_targets: dict[str, ValuationTarget] | None = None,
    result_horizons: dict[str, int | None] | None = None,
    request_blend: bool = False,
) -> MethodComparisonReport:
    """Compare method-specific results without blending (SPEC §13.1 / §13.5).

    If ``request_blend`` is True, still returns ENSEMBLE_UNCALIBRATED with
    combined_value=None (Phase 8 owns calibrated mixtures).
    """
    normalized: list[NormalizedMethodValue] = []
    skipped: list[dict[str, str]] = []
    for r in results:
        norm, reason = normalize_method_result(
            r,
            target=target,
            horizon=horizon,
            requested_output_basis=requested_output_basis,
        )
        if norm is None:
            skipped.append({"method_id": r.method_id, "reason": reason or "skipped"})
        else:
            # Identity must survive normalization
            assert norm.method_id == r.method_id
            assert norm.retained_identity is True
            normalized.append(norm)

    # Deterministic order
    normalized = sorted(normalized, key=lambda n: n.method_id)
    skipped = sorted(skipped, key=lambda s: s["method_id"])

    compat = check_combination_compatibility(
        results,
        target=target,
        horizon=horizon,
        requested_output_basis=requested_output_basis,
        result_targets=result_targets,
        result_horizons=result_horizons,
    )
    ensemble = refuse_uncalibrated_blend(
        results,
        target=target,
        horizon=horizon,
        requested_output_basis=requested_output_basis,
        result_targets=result_targets,
        result_horizons=result_horizons,
    )
    if request_blend:
        ensemble = {
            **ensemble,
            "blend_requested": True,
            "status": ClaimStatus.ENSEMBLE_UNCALIBRATED.value,
            "combined_value": None,
            "reason": ensemble["reason"] + " Blend was requested but refused.",
        }

    notes = (
        f"normalized={len(normalized)}; skipped={len(skipped)}; "
        f"compatible={compat.compatible}; ensemble={ensemble['status']}"
    )
    return MethodComparisonReport(
        target=target,
        horizon=horizon,
        requested_output_basis=requested_output_basis,
        method_results_retained=[r.method_id for r in results],
        normalized=normalized,
        skipped=skipped,
        disagreement=_disagreement(normalized),
        compatibility=compat,
        ensemble=ensemble,
        notes=notes,
    )
