"""Hard eligibility gates (SPEC §11.2). Phase 2: refuse before any valuation math."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from vms.methods.protocol import (
    FinancialPathBundle,
    MethodConfig,
    MethodDiagnostics,
    MethodResult,
    ValuationContext,
)
from vms.schemas.contracts import (
    MethodEligibilityStatus,
    MethodImplementationStatus,
    MethodRegistryEntry,
    ProfileLabel,
)


class GateReason(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    detail: str
    passed: bool


class EligibilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: str
    status: MethodEligibilityStatus
    eligible: bool
    reasons: list[GateReason] = Field(default_factory=list)
    soft_suitability: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Soft suitability dimension map (SPEC §11.3). Router attaches the full "
            "7-dimension vector after hard gates pass. Not ensemble weights."
        ),
    )


def evaluate_hard_gates(entry: MethodRegistryEntry, context: ValuationContext) -> EligibilityResult:
    """Apply hard gates. NEVER marks NOT_IMPLEMENTED methods as eligible to run."""
    reasons: list[GateReason] = []

    # Gate 0: implementation
    impl_ok = entry.implementation_status is MethodImplementationStatus.IMPLEMENTED and entry.enabled
    reasons.append(GateReason(
        code="METHOD_IMPLEMENTED_AND_ENABLED",
        detail=(f"implementation_status={entry.implementation_status.value} enabled={entry.enabled}"),
        passed=impl_ok,
    ))

    # Gate 1: target support
    target_ok = context.target in entry.supported_targets
    reasons.append(GateReason(
        code="TARGET_SUPPORTED",
        detail=f"target={context.target.value}; supported={[t.value for t in entry.supported_targets]}",
        passed=target_ok,
    ))

    # Gate 2: profile eligibility / exclusions
    primary = context.profile.primary_profile
    profile_ok = True
    if entry.eligible_profiles and primary not in entry.eligible_profiles:
        # HYBRID_OR_UNCLEAR / low confidence: do not invent eligibility
        profile_ok = False
    if primary is ProfileLabel.HYBRID_OR_UNCLEAR and entry.eligible_profiles:
        profile_ok = False
    for cond in entry.exclusion_conditions:
        if cond.startswith("profile_in:"):
            lab = cond.split(":", 1)[1]
            if primary.value == lab:
                profile_ok = False
                reasons.append(GateReason(
                    code="PROFILE_EXCLUSION",
                    detail=f"exclusion {cond} matched primary={primary.value}",
                    passed=False,
                ))
    reasons.append(GateReason(
        code="PROFILE_ELIGIBLE",
        detail=f"primary={primary.value}; eligible_profiles={[p.value for p in entry.eligible_profiles]}",
        passed=profile_ok,
    ))

    # Gate 3: required fields
    missing = [f for f in entry.required_fields if f not in context.available_fields]
    fields_ok = not missing
    reasons.append(GateReason(
        code="REQUIRED_FIELDS_PRESENT",
        detail=("ok" if fields_ok else f"missing={missing}"),
        passed=fields_ok,
    ))

    # Gate 4: data quality block
    dq_ok = not context.data_quality_blocked
    reasons.append(GateReason(
        code="DATA_QUALITY_NOT_BLOCKED",
        detail=f"data_quality_blocked={context.data_quality_blocked}",
        passed=dq_ok,
    ))

    # Low-confidence profile: may narrow eligibility (SPEC §7.4) — Phase 2: mark soft only
    soft: dict[str, float] = {}
    if context.profile.low_confidence:
        soft["conceptual_fit"] = 0.3
        soft["note_low_confidence_profile"] = 1.0
    elif profile_ok and target_ok:
        soft["conceptual_fit"] = 0.7

    hard_pass = impl_ok and target_ok and profile_ok and fields_ok and dq_ok
    if not impl_ok:
        status = MethodEligibilityStatus.INELIGIBLE
        # Still INELIGIBLE (not NOT_RUN) when gates evaluated and failed on implementation
    elif hard_pass:
        status = MethodEligibilityStatus.VALID  # would be runnable — Phase 2 none reach here
    else:
        status = MethodEligibilityStatus.INELIGIBLE

    return EligibilityResult(
        method_id=entry.method_id,
        status=status,
        eligible=hard_pass,
        reasons=reasons,
        soft_suitability=soft,
    )


def refuse_unimplemented_run(
    entry: MethodRegistryEntry,
    context: ValuationContext,
    *,
    financial_paths: FinancialPathBundle | None = None,
    config: MethodConfig | None = None,
) -> MethodResult:
    """Hard refuse: value_paths must not compute when gates fail / not implemented."""
    elig = evaluate_hard_gates(entry, context)
    if elig.eligible:
        # Should be unreachable in Phase 2 (no IMPLEMENTED methods)
        return MethodResult(
            method_id=entry.method_id,
            status=MethodEligibilityStatus.FAILED,
            reason_codes=["PHASE2_NO_METHOD_MATH"],
            detail="Phase 2 has no implemented valuation math; refusing to fabricate a value",
            output_basis=list(entry.output_basis),
        )
    codes = [r.code for r in elig.reasons if not r.passed]
    if entry.implementation_status is not MethodImplementationStatus.IMPLEMENTED:
        codes = ["METHOD_NOT_IMPLEMENTED", *codes]
    return MethodResult(
        method_id=entry.method_id,
        status=MethodEligibilityStatus.INELIGIBLE,
        reason_codes=codes or ["HARD_GATE_FAILED"],
        detail="; ".join(r.detail for r in elig.reasons if not r.passed) or "ineligible",
        output_basis=list(entry.output_basis),
    )


class DeclaredStubMethod:
    """Runtime stub for a declared-but-not-implemented registry entry.

    ``eligibility`` evaluates hard gates; ``value_paths`` always returns a
    structured refusal (never a fabricated value).
    """

    def __init__(self, entry: MethodRegistryEntry) -> None:
        self.entry = entry
        self.method_id = entry.method_id
        self.version = entry.version

    def eligibility(self, context: ValuationContext) -> EligibilityResult:
        return evaluate_hard_gates(self.entry, context)

    def value_paths(
        self,
        context: ValuationContext,
        financial_paths: FinancialPathBundle,
        config: MethodConfig,
    ) -> MethodResult:
        return refuse_unimplemented_run(
            self.entry, context, financial_paths=financial_paths, config=config,
        )

    def diagnostics(self, result: MethodResult) -> MethodDiagnostics:
        return MethodDiagnostics(method_id=self.method_id, messages=list(result.reason_codes) + [result.detail])
