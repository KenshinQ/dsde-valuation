"""Soft suitability diagnostics (SPEC §11.3).

Dimensions are separately visible; there is no single opaque score.
Suitability is a diagnostic — it is NOT an ensemble weight (SPEC §11.3 / §22.6).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vms.methods.protocol import ValuationContext
from vms.schemas.contracts import MethodRegistryEntry, ProfileLabel

# Ordered dimension keys (SPEC §11.3). Higher is always "more suitable".
# ``fragility`` is scored as resilience: 1.0 = robust / low fragility, 0.0 = fragile.
SUITABILITY_DIMENSIONS: tuple[str, ...] = (
    "conceptual_fit",
    "data_quality",
    "denominator_stability",
    "peer_sample_support",
    "parameter_identifiability",
    "calibration_evidence",
    "fragility",
)


class SoftSuitability(BaseModel):
    """Per-method soft suitability vector. Never collapse to one opaque number."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimensions: dict[str, float] = Field(default_factory=dict)
    rationales: dict[str, str] = Field(default_factory=dict)
    # Explicit non-weight marker so consumers cannot mistake this for ensemble weights
    ensemble_weight: None = None
    note: str = (
        "soft suitability diagnostics only; not ensemble weights "
        "(SPEC §11.3 / §13.3 / §22.6)"
    )

    @model_validator(mode="after")
    def _require_all_dimensions(self) -> "SoftSuitability":
        missing = [d for d in SUITABILITY_DIMENSIONS if d not in self.dimensions]
        if missing:
            raise ValueError(f"soft suitability missing dimensions: {missing}")
        for k, v in self.dimensions.items():
            if k not in SUITABILITY_DIMENSIONS:
                raise ValueError(f"unknown suitability dimension: {k}")
            if not (0.0 <= float(v) <= 1.0):
                raise ValueError(f"dimension {k}={v} out of [0,1]")
        return self

    def as_dict(self) -> dict[str, float]:
        return {d: float(self.dimensions[d]) for d in SUITABILITY_DIMENSIONS}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def compute_soft_suitability(
    entry: MethodRegistryEntry,
    context: ValuationContext,
    *,
    hard_gate_passed: bool,
) -> SoftSuitability | None:
    """Compute soft dimensions only after hard gates pass (SPEC §11.3).

    Returns None when hard gates failed — soft scores must not launder ineligibility.
    """
    if not hard_gate_passed:
        return None

    dims: dict[str, float] = {}
    rats: dict[str, str] = {}
    primary = context.profile.primary_profile

    # conceptual_fit
    if context.profile.low_confidence or primary is ProfileLabel.HYBRID_OR_UNCLEAR:
        dims["conceptual_fit"] = 0.35
        rats["conceptual_fit"] = (
            f"low_confidence={context.profile.low_confidence}; "
            f"primary={primary.value}"
        )
    elif entry.eligible_profiles and primary in entry.eligible_profiles:
        dims["conceptual_fit"] = 0.85
        rats["conceptual_fit"] = f"primary={primary.value} in eligible_profiles"
    else:
        dims["conceptual_fit"] = 0.55
        rats["conceptual_fit"] = (
            f"primary={primary.value}; eligible_profiles empty or open set"
        )

    # data_quality
    if context.data_quality_blocked:
        dims["data_quality"] = 0.0
        rats["data_quality"] = "data_quality_blocked=true"
    else:
        missing = [f for f in entry.required_fields if f not in context.available_fields]
        if not entry.required_fields:
            dims["data_quality"] = 0.6
            rats["data_quality"] = "no required_fields declared; neutral completeness"
        elif not missing:
            dims["data_quality"] = 0.9
            rats["data_quality"] = "all required_fields present"
        else:
            # Should not reach here if hard gates require fields — defensive
            frac = 1.0 - (len(missing) / max(len(entry.required_fields), 1))
            dims["data_quality"] = _clamp01(0.2 + 0.6 * frac)
            rats["data_quality"] = f"missing_required={missing}"

    # denominator_stability (heuristic; method plugins may refine later)
    if entry.method_id in {"pe", "ev_ebit", "ev_ebitda", "ev_sales", "pb"}:
        dims["denominator_stability"] = 0.55
        rats["denominator_stability"] = (
            "multiple denominator; stability assessed at apply-time; "
            "Phase-7 prior=0.55"
        )
    elif entry.method_id in {"fcff_dcf", "fcfe_dcf", "ddm", "residual_income"}:
        dims["denominator_stability"] = 0.7
        rats["denominator_stability"] = (
            "cash-flow/RI discount-rate path; Phase-7 prior=0.7 pending path diagnostics"
        )
    else:
        dims["denominator_stability"] = 0.6
        rats["denominator_stability"] = "asset/NAV-style; Phase-7 prior=0.6"

    # peer_sample_support
    if entry.method_id in {"pe", "pb", "ev_ebit", "ev_ebitda", "ev_sales"}:
        if context.peer_count <= 0:
            dims["peer_sample_support"] = 0.15
            rats["peer_sample_support"] = "peer_count=0"
        elif context.peer_count < 5:
            dims["peer_sample_support"] = 0.4
            rats["peer_sample_support"] = f"peer_count={context.peer_count} (<5)"
        else:
            dims["peer_sample_support"] = _clamp01(0.5 + min(context.peer_count, 20) / 40.0)
            rats["peer_sample_support"] = f"peer_count={context.peer_count}"
    else:
        dims["peer_sample_support"] = 0.5
        rats["peer_sample_support"] = "method does not require peer cross-section; neutral=0.5"

    # parameter_identifiability — Phase 7: no OOS calibration yet → modest prior
    if entry.assumption_schema_ids:
        dims["parameter_identifiability"] = 0.45
        rats["parameter_identifiability"] = (
            f"assumptions={list(entry.assumption_schema_ids)}; "
            "identifiability not yet evidenced (Phase 7)"
        )
    else:
        dims["parameter_identifiability"] = 0.35
        rats["parameter_identifiability"] = "no assumption_schema_ids; low identifiability prior"

    # calibration_evidence — Phase 7/8: always low until walk-forward
    dims["calibration_evidence"] = 0.0
    rats["calibration_evidence"] = (
        "no out-of-sample calibration evidence in Phase 7; "
        "do not treat suitability as calibrated weight"
    )

    # fragility (resilience score): low confidence / hybrid → more fragile
    if context.profile.low_confidence:
        dims["fragility"] = 0.35
        rats["fragility"] = "low_confidence profile → higher fragility (score=resilience)"
    elif primary is ProfileLabel.DISTRESSED_OR_TURNAROUND:
        dims["fragility"] = 0.3
        rats["fragility"] = "distressed/turnaround → high fragility"
    else:
        dims["fragility"] = 0.65
        rats["fragility"] = "baseline resilience prior=0.65 (1=robust)"

    return SoftSuitability(dimensions=dims, rationales=rats)
