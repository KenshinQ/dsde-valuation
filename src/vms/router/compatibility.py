"""Compatibility before combination (SPEC §13.2).

Phase 7 enforces the checker and refuses incompatible blends.
Phase 8 owns mixture weights in vms.ensemble; this module remains the §13.2 gate.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.methods.protocol import MethodResult
from vms.schemas.contracts import (
    ClaimStatus,
    MethodEligibilityStatus,
    OutputBasis,
    ValuationTarget,
)


class CompatibilityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    detail: str
    method_ids: list[str] = Field(default_factory=list)


class CompatibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    compatible: bool
    target: ValuationTarget
    horizon: int | None
    requested_output_basis: OutputBasis
    issues: list[CompatibilityIssue] = Field(default_factory=list)
    combination_status: str = ClaimStatus.ENSEMBLE_UNCALIBRATED.value
    note: str = (
        "Compatibility gate (SPEC §13.2). Production calibrated ensemble "
        "requires vms.ensemble checklist (SPEC §13.3). Suitability ≠ weight."
    )


def _result_bases(result: MethodResult) -> set[OutputBasis]:
    return set(result.output_basis or [])


def _has_scalar_for_basis(result: MethodResult, basis: OutputBasis) -> bool:
    """Whether the result carries a comparable scalar for the requested basis."""
    vals = result.values or {}
    if basis is OutputBasis.EQUITY:
        return "equity_value" in vals or "nav_equity" in vals
    if basis is OutputBasis.EV:
        return "enterprise_value" in vals
    if basis is OutputBasis.NAV:
        return "nav" in vals or "equity_value" in vals or "nav_equity" in vals
    if basis is OutputBasis.PER_SHARE:
        return "value_per_share" in vals
    if basis is OutputBasis.MARKET_PRICE:
        return "market_price" in vals or "exit_price" in vals
    return False


def check_combination_compatibility(
    results: list[MethodResult],
    *,
    target: ValuationTarget,
    horizon: int | None = None,
    requested_output_basis: OutputBasis = OutputBasis.EQUITY,
    result_targets: dict[str, ValuationTarget] | None = None,
    result_horizons: dict[str, int | None] | None = None,
) -> CompatibilityReport:
    """Return whether method results may enter the *same* ensemble/combination.

    Incompatible target / horizon / output basis → compatible=False with reasons.
    Even when compatible, Phase 7 leaves combination_status=ENSEMBLE_UNCALIBRATED.
    """
    issues: list[CompatibilityIssue] = []
    result_targets = result_targets or {}
    result_horizons = result_horizons or {}

    # Intrinsic current vs future market price cannot mix
    if target is ValuationTarget.MARKET_EXIT_PRICE:
        # Combining MARKET_EXIT_PRICE with fundamental results is forbidden at call site;
        # also flag if any component declares a different target.
        pass

    valid = [
        r for r in results
        if r.status in {MethodEligibilityStatus.VALID, MethodEligibilityStatus.LOW_CONFIDENCE}
        and r.values
    ]

    if len(valid) < 2:
        # Trivially "compatible" for a single or empty set — still uncalibrated / not a blend
        return CompatibilityReport(
            compatible=True,
            target=target,
            horizon=horizon,
            requested_output_basis=requested_output_basis,
            issues=[],
            combination_status=ClaimStatus.ENSEMBLE_UNCALIBRATED.value,
            note=(
                "fewer than two valid results; nothing to combine. "
                "Compatibility gate alone never fabricates a blend."
            ),
        )

    for r in valid:
        mid = r.method_id
        rt = result_targets.get(mid, target)
        if rt is not target:
            issues.append(CompatibilityIssue(
                code="TARGET_MISMATCH",
                detail=f"method target={rt.value} ≠ requested {target.value}",
                method_ids=[mid],
            ))
        # Current fundamental cannot mix with market exit
        if rt is ValuationTarget.MARKET_EXIT_PRICE and target is not ValuationTarget.MARKET_EXIT_PRICE:
            issues.append(CompatibilityIssue(
                code="INTRINSIC_VS_MARKET_PRICE",
                detail=(
                    "current/fundamental target cannot be averaged with "
                    "MARKET_EXIT_PRICE (SPEC §13.2)"
                ),
                method_ids=[mid],
            ))
        if target is ValuationTarget.MARKET_EXIT_PRICE and rt is not ValuationTarget.MARKET_EXIT_PRICE:
            issues.append(CompatibilityIssue(
                code="INTRINSIC_VS_MARKET_PRICE",
                detail="MARKET_EXIT_PRICE target cannot include fundamental-only method",
                method_ids=[mid],
            ))

        rh = result_horizons.get(mid, horizon)
        if rh != horizon:
            issues.append(CompatibilityIssue(
                code="HORIZON_MISMATCH",
                detail=f"method horizon={rh} ≠ requested {horizon}",
                method_ids=[mid],
            ))

        bases = _result_bases(r)
        if requested_output_basis not in bases and not _has_scalar_for_basis(r, requested_output_basis):
            # Special case: EV-only method asked for EQUITY without bridge evidence
            if (
                requested_output_basis is OutputBasis.EQUITY
                and OutputBasis.EV in bases
                and "equity_value" not in (r.values or {})
            ):
                issues.append(CompatibilityIssue(
                    code="EV_EQUITY_BRIDGE_REQUIRED",
                    detail=(
                        "EV-basis method lacks equity_value bridge; "
                        "cannot combine with EQUITY target before bridge (SPEC §13.2)"
                    ),
                    method_ids=[mid],
                ))
            else:
                issues.append(CompatibilityIssue(
                    code="OUTPUT_BASIS_INCOMPATIBLE",
                    detail=(
                        f"requested_basis={requested_output_basis.value}; "
                        f"method_bases={[b.value for b in bases]}; "
                        f"no comparable scalar for basis"
                    ),
                    method_ids=[mid],
                ))

    # Cross-check: forbid mixing MARKET_EXIT_PRICE-labeled results with others when
    # the requested target is fundamental / relative / NAV
    if target in {
        ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        ValuationTarget.FUNDAMENTAL_VALUE_HORIZON,
        ValuationTarget.RELATIVE_VALUE_CURRENT,
        ValuationTarget.ASSET_NAV,
    }:
        for r in valid:
            if OutputBasis.MARKET_PRICE in _result_bases(r) and not _has_scalar_for_basis(
                r, requested_output_basis,
            ):
                issues.append(CompatibilityIssue(
                    code="INTRINSIC_VS_MARKET_PRICE",
                    detail="MARKET_PRICE output basis mixed into fundamental comparison",
                    method_ids=[r.method_id],
                ))

    compatible = not issues
    status = (
        ClaimStatus.ENSEMBLE_UNCALIBRATED.value
        if compatible
        else "NOT_COMBINED_INCOMPATIBLE"
    )
    return CompatibilityReport(
        compatible=compatible,
        target=target,
        horizon=horizon,
        requested_output_basis=requested_output_basis,
        issues=issues,
        combination_status=status,
    )


def refuse_uncalibrated_blend(
    results: list[MethodResult],
    *,
    target: ValuationTarget,
    horizon: int | None = None,
    requested_output_basis: OutputBasis = OutputBasis.EQUITY,
    **kwargs: Any,
) -> dict[str, Any]:
    """Explicit refusal of production blend (Phase 7 / SPEC §13.3 exploratory ban).

    Returns a structured status payload — never a blended fair-value number.
    """
    compat = check_combination_compatibility(
        results,
        target=target,
        horizon=horizon,
        requested_output_basis=requested_output_basis,
        **kwargs,
    )
    return {
        "combined_value": None,
        "mixture_weights": None,
        "status": ClaimStatus.ENSEMBLE_UNCALIBRATED.value,
        "compatible": compat.compatible,
        "compatibility": compat.model_dump(mode="json"),
        "reason": (
            "Uncalibrated production blend refused; "
            "report method-specific results and disagreement only "
            "(SPEC §13.3). Equal-weight or suitability-proportional "
            "blends are PRIOR_ONLY exploratory baselines, not "
            "ENSEMBLE_CALIBRATED (SPEC §22.6–22.7)."
        ),
        "investment_value": ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value,
    }
