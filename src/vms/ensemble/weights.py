"""Mixture weight artifacts and validation (SPEC §13.3 / §21.2).

Weights must be finite, non-negative, and sum to one. Intrinsic-value and
market-outcome weight artifacts are separate and must not be reused across
targets (SPEC §13.4).
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vms.ensemble.protocols import (
    EnsembleMode,
    WeightProtocol,
    WeightProtocolId,
    make_market_outcome_protocol,
    make_prior_equal_protocol,
)
from vms.schemas.contracts import ValuationTarget

WEIGHT_SUM_TOL = 1e-9


class WeightValidationError(ValueError):
    """Raised when weights violate non-negativity / unit-sum / protocol rules."""


def validate_weight_map(weights: dict[str, float]) -> dict[str, float]:
    """Return a normalized copy after checking finite, ≥0, sum≈1."""
    if not weights:
        raise WeightValidationError("empty weight map")
    cleaned: dict[str, float] = {}
    for mid, w in weights.items():
        if not isinstance(mid, str) or not mid:
            raise WeightValidationError(f"invalid method_id={mid!r}")
        try:
            fw = float(w)
        except (TypeError, ValueError) as exc:
            raise WeightValidationError(f"non-numeric weight for {mid}: {w!r}") from exc
        if not math.isfinite(fw):
            raise WeightValidationError(f"non-finite weight for {mid}: {fw}")
        if fw < 0:
            raise WeightValidationError(f"negative weight for {mid}: {fw}")
        cleaned[mid] = fw
    total = sum(cleaned.values())
    if abs(total - 1.0) > WEIGHT_SUM_TOL:
        raise WeightValidationError(
            f"weights must sum to 1 within {WEIGHT_SUM_TOL}; got sum={total}"
        )
    # Snap tiny float noise so persisted artifacts are clean
    if abs(total - 1.0) > 0:
        # renormalize only if within tolerance already checked
        cleaned = {k: v / total for k, v in cleaned.items()}
    return dict(sorted(cleaned.items()))


class WeightArtifact(BaseModel):
    """Persisted weight vector with named protocol and target (SPEC §13.3–13.4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_kind: Literal["intrinsic_value_weights", "MARKET_OUTCOME_WEIGHTING"]
    protocol: WeightProtocol
    weights: dict[str, float] = Field(default_factory=dict)
    method_ids: list[str] = Field(default_factory=list)
    calibration_sample_size: int = 0
    oos_evaluated: bool = False
    note: str = ""

    @model_validator(mode="after")
    def _check_consistency(self) -> WeightArtifact:
        validate_weight_map(self.weights)
        if set(self.method_ids) != set(self.weights):
            raise ValueError("method_ids must match weights keys")
        if self.artifact_kind != self.protocol.artifact_kind:
            raise ValueError(
                f"artifact_kind={self.artifact_kind} ≠ protocol.artifact_kind="
                f"{self.protocol.artifact_kind}"
            )
        if (
            self.artifact_kind == "MARKET_OUTCOME_WEIGHTING"
            and self.protocol.protocol_id is not WeightProtocolId.MARKET_OUTCOME_WEIGHTING
        ):
            raise ValueError("MARKET_OUTCOME artifact requires MARKET_OUTCOME protocol")
        if (
            self.artifact_kind == "intrinsic_value_weights"
            and self.protocol.protocol_id is WeightProtocolId.MARKET_OUTCOME_WEIGHTING
        ):
            raise ValueError(
                "MARKET_OUTCOME_WEIGHTING cannot be stored as intrinsic_value_weights "
                "(SPEC §13.4)"
            )
        return self

    @property
    def is_calibrated_claim(self) -> bool:
        return (
            self.protocol.mode is EnsembleMode.PRODUCTION_CALIBRATED
            and self.oos_evaluated
            and self.calibration_sample_size > 0
        )


def equal_prior_weights(
    method_ids: list[str],
    *,
    target: ValuationTarget,
) -> WeightArtifact:
    """Exploratory equal-weight PRIOR_ONLY baseline — never a calibrated claim."""
    ids = sorted({m for m in method_ids if m})
    if not ids:
        raise WeightValidationError("equal_prior_weights requires ≥1 method_id")
    w = 1.0 / len(ids)
    weights = {m: w for m in ids}
    protocol = make_prior_equal_protocol(target)
    return WeightArtifact(
        artifact_kind="intrinsic_value_weights",
        protocol=protocol,
        weights=validate_weight_map(weights),
        method_ids=ids,
        calibration_sample_size=0,
        oos_evaluated=False,
        note=(
            "PRIOR_ONLY equal-weight exploratory baseline (SPEC §13.3 / §22.7). "
            "Not ENSEMBLE_CALIBRATED."
        ),
    )


def market_outcome_weight_artifact(
    weights: dict[str, float],
    *,
    target: ValuationTarget,
    calibration_sample_size: int = 0,
    oos_evaluated: bool = False,
) -> WeightArtifact:
    """Build a MARKET_OUTCOME_WEIGHTING artifact (separate from intrinsic)."""
    cleaned = validate_weight_map(weights)
    protocol = make_market_outcome_protocol(
        target,
        calibrated=bool(oos_evaluated and calibration_sample_size > 0),
    )
    # Even if caller claims calibrated, Phase 8 build layer must still refuse
    # ENSEMBLE_CALIBRATED without the full §13.3 / §17.4 checklist.
    if not (oos_evaluated and calibration_sample_size > 0):
        protocol = make_market_outcome_protocol(target, calibrated=False)
    return WeightArtifact(
        artifact_kind="MARKET_OUTCOME_WEIGHTING",
        protocol=protocol,
        weights=cleaned,
        method_ids=sorted(cleaned.keys()),
        calibration_sample_size=calibration_sample_size,
        oos_evaluated=oos_evaluated,
        note=(
            "MARKET_OUTCOME_WEIGHTING artifact (SPEC §13.4). "
            "Must not be reused as intrinsic-value reliability weights."
        ),
    )


def refuse_reuse_market_as_intrinsic(artifact: WeightArtifact) -> None:
    """Raise if a market-outcome artifact is presented as intrinsic weights."""
    if artifact.artifact_kind == "MARKET_OUTCOME_WEIGHTING":
        raise WeightValidationError(
            "MARKET_OUTCOME_WEIGHTING must not be reused as intrinsic-value "
            "reliability weights (SPEC §13.4)"
        )
    if artifact.protocol.protocol_id is WeightProtocolId.MARKET_OUTCOME_WEIGHTING:
        raise WeightValidationError(
            "protocol MARKET_OUTCOME_WEIGHTING cannot authorize intrinsic mixture"
        )


__all__ = [
    "WEIGHT_SUM_TOL",
    "WeightValidationError",
    "WeightArtifact",
    "validate_weight_map",
    "equal_prior_weights",
    "market_outcome_weight_artifact",
    "refuse_reuse_market_as_intrinsic",
]
