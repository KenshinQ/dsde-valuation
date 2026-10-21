"""Routing procedure (SPEC §11.4). Phase 4: may run eligible implemented methods; never averages."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.methods.eligibility import EligibilityResult
from vms.methods.protocol import MethodResult, ValuationContext
from vms.methods.registry import MethodRegistry
from vms.profiles.report import ProfileReport
from vms.schemas.contracts import (
    ClaimStatus,
    MethodEligibilityStatus,
    MethodStatusRecord,
    ValuationTarget,
)


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
    method_status: list[MethodStatusRecord] = Field(default_factory=list)
    attempted_runs: list[MethodResult] = Field(default_factory=list)
    investment_value: str = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    notes: str = ""


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
) -> RouteReport:
    """Enumerate target methods, apply hard gates, optionally attempt value_paths.

    When ``attempt_value_paths`` is True without a statements path bundle, plugins
    must refuse with structured codes (never fabricate). With a real bundle and
    ``context_loaded``, eligible Phase-4 methods may return values — still no ensemble.
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
    )
    candidates = [e.method_id for e in registry.for_target(target)]
    eligibility = registry.evaluate_all(ctx)
    # Prefer plugin.eligibility when it adds method-specific gates (e.g. DDM payout)
    refined: list[EligibilityResult] = []
    for e in registry.for_target(target):
        plugin = registry.plugin(e.method_id)
        if plugin is not None and hasattr(plugin, "eligibility"):
            refined.append(plugin.eligibility(ctx))
        else:
            refined.append(next(r for r in eligibility if r.method_id == e.method_id))
    eligibility = refined
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
        for e in registry.for_target(target):
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
            # Anti-pattern: stub/unimplemented must not return VALID with values
            if (
                e.implementation_status.value != "IMPLEMENTED"
                and last.status is MethodEligibilityStatus.VALID
                and last.values
            ):
                raise RuntimeError(
                    f"anti-pattern: method {e.method_id} returned values before implementation"
                )

    notes = (
        f"candidates={len(candidates)}; coverage={coverage}; "
        f"eligible_implemented={sum(1 for e in eligibility if e.eligible)}"
    )
    if coverage == "INSUFFICIENT_METHOD_COVERAGE":
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
        method_status=rows,
        attempted_runs=attempted,
        notes=notes,
    )
