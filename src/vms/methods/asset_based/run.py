"""Run eligible Phase-6 RIM/NAV/SOTP methods via the router (no ensemble)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.methods.protocol import MethodConfig, MethodResult, ValuationContext
from vms.methods.registry import MethodRegistry
from vms.profiles.report import ProfileReport
from vms.router.route import RouteReport, route_methods
from vms.schemas.config import LoadedConfig
from vms.schemas.contracts import ClaimStatus, MethodEligibilityStatus, ValuationTarget

PHASE6_METHODS = ("residual_income", "nav", "sotp")


class MethodRunBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    route: RouteReport
    results: list[MethodResult] = Field(default_factory=list)
    eligible_run: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    investment_value: str = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    ensemble: None = None
    notes: str = ""


def run_eligible_phase6_methods(
    *,
    registry: MethodRegistry,
    profile: ProfileReport,
    target: ValuationTarget,
    loaded: LoadedConfig,
    available_fields: frozenset[str] | set[str] | None = None,
    peer_count: int = 0,
    data_quality_blocked: bool = False,
    financial_paths: Any = None,
    method_assumptions: dict[str, dict[str, Any]] | None = None,
    rim_inputs: dict[str, Any] | None = None,
    nav_inputs: dict[str, Any] | None = None,
    sotp_inputs: dict[str, Any] | None = None,
    subject_metrics: dict[str, Any] | None = None,
    as_of: str | None = None,
) -> MethodRunBundle:
    """Route, then run only eligible implemented Phase-6 methods. Never averages."""
    ctx = ValuationContext(
        instrument_id=profile.instrument_id,
        as_of=as_of or profile.as_of,
        target=target,
        profile=profile,
        available_fields=frozenset(available_fields or ()),
        peer_count=peer_count,
        data_quality_blocked=data_quality_blocked,
        loaded=loaded,
        subject_metrics=dict(subject_metrics or {}),
        rim_inputs=dict(rim_inputs or {}),
        nav_inputs=dict(nav_inputs or {}),
        sotp_inputs=dict(sotp_inputs or {}),
    )
    route = route_methods(
        registry=registry,
        profile=profile,
        target=target,
        available_fields=available_fields,
        peer_count=peer_count,
        data_quality_blocked=data_quality_blocked,
        attempt_value_paths=False,
        context_loaded=loaded,
    )
    assumptions = method_assumptions or {}
    results: list[MethodResult] = []
    eligible_run: list[str] = []
    skipped: list[str] = []

    for elig in route.eligibility:
        if elig.method_id not in PHASE6_METHODS:
            skipped.append(elig.method_id)
            continue
        plugin = registry.plugin(elig.method_id)
        if plugin is None:
            skipped.append(elig.method_id)
            continue
        cfg = MethodConfig(
            method_id=elig.method_id,
            assumptions=dict(assumptions.get(elig.method_id, {})),
        )
        result = plugin.value_paths(ctx, financial_paths, cfg)
        results.append(result)
        if result.status is MethodEligibilityStatus.VALID and result.values:
            eligible_run.append(elig.method_id)
        else:
            skipped.append(elig.method_id)

    notes = (
        f"ran={eligible_run}; skipped/ineligible={skipped}; "
        f"coverage={route.coverage_status}; ensemble=None (Phase 8)"
    )
    return MethodRunBundle(
        route=route,
        results=results,
        eligible_run=eligible_run,
        skipped=skipped,
        notes=notes,
    )
