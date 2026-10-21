"""Deterministic routing procedure (SPEC §11.4). Phase 7 hardens logging.

Logs every considered method, hard-gate result, soft suitability dimensions,
selected/runnable status and reason. Never fabricates a default DCF.
Never builds a calibrated ensemble (Phase 8).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.methods.eligibility import EligibilityResult, GateReason
from vms.methods.protocol import MethodResult, ValuationContext
from vms.methods.registry import MethodRegistry
from vms.profiles.report import ProfileReport
from vms.router.suitability import SoftSuitability, compute_soft_suitability
from vms.schemas.contracts import (
    ClaimStatus,
    DataQualityGateStatus,
    MethodEligibilityStatus,
    MethodStatusRecord,
    ValuationTarget,
)


class MethodConsideration(BaseModel):
    """One method's full routing log row (feeds method_eligibility.json)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: str
    considered: bool = True
    hard_gate_passed: bool
    hard_gate_reasons: list[GateReason] = Field(default_factory=list)
    soft_suitability: SoftSuitability | None = None
    soft_suitability_dimensions: dict[str, float] = Field(default_factory=dict)
    selected_runnable: bool
    reason: str
    status: MethodEligibilityStatus


class RouteReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    as_of: str
    target: ValuationTarget
    profile_primary: str
    profile_low_confidence: bool
    coverage_status: str
    candidates: list[str] = Field(default_factory=list)
    eligibility: list[EligibilityResult] = Field(default_factory=list)
    considerations: list[MethodConsideration] = Field(default_factory=list)
    method_status: list[MethodStatusRecord] = Field(default_factory=list)
    attempted_runs: list[MethodResult] = Field(default_factory=list)
    investment_value: str = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    notes: str = ""
    routing_deterministic: bool = True


def _eligibility_for_entry(registry: MethodRegistry, method_id: str, ctx: ValuationContext) -> EligibilityResult:
    plugin = registry.plugin(method_id)
    if plugin is not None and hasattr(plugin, "eligibility"):
        return plugin.eligibility(ctx)
    entry = registry.get(method_id)
    assert entry is not None
    from vms.methods.eligibility import evaluate_hard_gates
    return evaluate_hard_gates(entry, ctx)


def _consideration_from_eligibility(
    registry: MethodRegistry,
    elig: EligibilityResult,
    ctx: ValuationContext,
) -> MethodConsideration:
    entry = registry.get(elig.method_id)
    soft: SoftSuitability | None = None
    if elig.eligible and entry is not None:
        soft = compute_soft_suitability(entry, ctx, hard_gate_passed=True)
    elif elig.eligible:
        soft = None

    # Prefer freshly computed SoftSuitability; fall back to legacy dict on EligibilityResult
    dims: dict[str, float] = {}
    if soft is not None:
        dims = soft.as_dict()
    elif elig.soft_suitability:
        # Legacy partial dict — do not invent missing dims as opaque score
        dims = {k: float(v) for k, v in elig.soft_suitability.items() if isinstance(v, (int, float))}

    if elig.eligible:
        reason = "hard_gates_passed; soft_suitability_attached; runnable"
        status = MethodEligibilityStatus.VALID
    else:
        failed = [r.code for r in elig.reasons if not r.passed]
        reason = "hard_gate_failed: " + (",".join(failed) if failed else "INELIGIBLE")
        status = MethodEligibilityStatus.INELIGIBLE

    return MethodConsideration(
        method_id=elig.method_id,
        considered=True,
        hard_gate_passed=bool(elig.eligible),
        hard_gate_reasons=list(elig.reasons),
        soft_suitability=soft,
        soft_suitability_dimensions=dims,
        selected_runnable=bool(elig.eligible),
        reason=reason,
        status=status,
    )


def route_methods(
    *,
    registry: MethodRegistry,
    profile: ProfileReport,
    target: ValuationTarget,
    available_fields: frozenset[str] | set[str] | None = None,
    peer_count: int = 0,
    data_quality_blocked: bool = False,
    attempt_value_paths: bool = False,
    context_loaded: Any = None,
    financial_paths: Any = None,
    dividend_history: tuple[float, ...] = (),
    net_income_history: tuple[float, ...] = (),
    subject_metrics: dict[str, Any] | None = None,
    peer_observations: tuple[Any, ...] = (),
    rim_inputs: dict[str, Any] | None = None,
    nav_inputs: dict[str, Any] | None = None,
    sotp_inputs: dict[str, Any] | None = None,
) -> RouteReport:
    """Enumerate target methods, apply hard gates, attach soft suitability.

    When ``attempt_value_paths`` is True without a statements path bundle, plugins
    must refuse with structured codes (never fabricate). With a real bundle and
    ``context_loaded``, eligible methods may return values — still no ensemble.
    """
    ctx = ValuationContext(
        instrument_id=profile.instrument_id,
        as_of=profile.as_of,
        target=target,
        profile=profile,
        available_fields=frozenset(available_fields or ()),
        peer_count=peer_count,
        data_quality_blocked=data_quality_blocked,
        loaded=context_loaded,
        dividend_history=dividend_history,
        net_income_history=net_income_history,
        subject_metrics=dict(subject_metrics or {}),
        peer_observations=peer_observations,
        rim_inputs=dict(rim_inputs or {}),
        nav_inputs=dict(nav_inputs or {}),
        sotp_inputs=dict(sotp_inputs or {}),
    )

    # Deterministic candidate order by method_id
    entries = sorted(registry.for_target(target), key=lambda e: e.method_id)
    candidates = [e.method_id for e in entries]

    eligibility: list[EligibilityResult] = []
    considerations: list[MethodConsideration] = []
    for e in entries:
        elig = _eligibility_for_entry(registry, e.method_id, ctx)
        # Attach full soft suitability onto a new EligibilityResult when eligible
        if elig.eligible:
            soft = compute_soft_suitability(e, ctx, hard_gate_passed=True)
            soft_dict = soft.as_dict() if soft is not None else {}
            elig = EligibilityResult(
                method_id=elig.method_id,
                status=elig.status,
                eligible=elig.eligible,
                reasons=list(elig.reasons),
                soft_suitability=soft_dict,
            )
        eligibility.append(elig)
        considerations.append(_consideration_from_eligibility(registry, elig, ctx))

    coverage, rows = registry.coverage_status(eligibility)
    rows = [
        MethodStatusRecord(
            method_id=r.method_id, status=r.status, reason=r.reason, target=target,
        )
        for r in rows
    ]

    attempted: list[MethodResult] = []
    if attempt_value_paths:
        from vms.methods.protocol import FinancialPathBundle, MethodConfig
        paths = financial_paths if financial_paths is not None else FinancialPathBundle()
        for e in entries:
            plugin = registry.plugin(e.method_id)
            assert plugin is not None
            attempted.append(
                plugin.value_paths(
                    ctx,
                    paths,
                    MethodConfig(method_id=e.method_id),
                )
            )
            last = attempted[-1]
            if (
                e.implementation_status.value != "IMPLEMENTED"
                and last.status is MethodEligibilityStatus.VALID
                and last.values
            ):
                raise RuntimeError(
                    f"anti-pattern: method {e.method_id} returned values before implementation"
                )

    # Coverage gap must never invent a default FCFF (SPEC §11.4 / §20 Phase 7 AC5)
    if coverage == DataQualityGateStatus.INSUFFICIENT_METHOD_COVERAGE.value:
        # Ensure no accidental promotion of fcff_dcf
        for c in considerations:
            if c.method_id == "fcff_dcf" and c.selected_runnable:
                raise RuntimeError(
                    "anti-pattern: fcff_dcf selected under INSUFFICIENT_METHOD_COVERAGE"
                )

    notes = (
        f"candidates={len(candidates)}; coverage={coverage}; "
        f"eligible_implemented={sum(1 for e in eligibility if e.eligible)}; "
        f"considerations={len(considerations)}"
    )
    if coverage == DataQualityGateStatus.INSUFFICIENT_METHOD_COVERAGE.value:
        notes += "; no eligible implemented method — not defaulting to DCF"

    return RouteReport(
        instrument_id=profile.instrument_id,
        as_of=profile.as_of,
        target=target,
        profile_primary=profile.primary_profile.value,
        profile_low_confidence=profile.low_confidence,
        coverage_status=coverage,
        candidates=candidates,
        eligibility=eligibility,
        considerations=considerations,
        method_status=rows,
        attempted_runs=attempted,
        notes=notes,
        routing_deterministic=True,
    )


def method_eligibility_payload(report: RouteReport, *, run_id: str | None = None) -> dict[str, Any]:
    """Serialize routing log for method_eligibility.json (SPEC §16.3)."""
    return {
        "run_id": run_id,
        "instrument_id": report.instrument_id,
        "as_of": report.as_of,
        "target": report.target.value,
        "profile_primary": report.profile_primary,
        "profile_low_confidence": report.profile_low_confidence,
        "coverage_status": report.coverage_status,
        "candidates": list(report.candidates),
        "methods": [c.model_dump(mode="json") for c in report.considerations],
        "method_status": [m.model_dump(mode="json") for m in report.method_status],
        "investment_value": report.investment_value,
        "routing_deterministic": report.routing_deterministic,
        "notes": report.notes,
    }
