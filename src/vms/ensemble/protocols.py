"""Named, versioned ensemble weight protocols (SPEC §13.3–13.4).

Equal-weight and suitability-proportional blends are PRIOR_ONLY / research
baselines only. They must never be labeled ENSEMBLE_CALIBRATED without OOS
evidence (SPEC §22.6–22.7). Intrinsic-value and market-outcome protocols are
distinct artifacts and must not be reused across targets.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from vms.schemas.contracts import ValuationTarget


class WeightProtocolId(str, Enum):
    """Protocol identifiers. Presence ≠ production calibration."""

    PRIOR_ONLY_EQUAL_WEIGHT = "PRIOR_ONLY_EQUAL_WEIGHT"
    PRIOR_ONLY_SUITABILITY_PROPORTIONAL = "PRIOR_ONLY_SUITABILITY_PROPORTIONAL"
    INTRINSIC_VALUE_WEIGHTING = "INTRINSIC_VALUE_WEIGHTING"
    MARKET_OUTCOME_WEIGHTING = "MARKET_OUTCOME_WEIGHTING"


class ScoringRule(str, Enum):
    """Declared scoring rule for the weight protocol (SPEC §13.4)."""

    NONE_PRIOR = "NONE_PRIOR"
    LOG_SCORE = "LOG_SCORE"
    CRPS = "CRPS"
    BRIER = "BRIER"


class EnsembleMode(str, Enum):
    """How the mixture was (or was not) authorized."""

    PRIOR_ONLY = "PRIOR_ONLY"
    PRODUCTION_REFUSED = "PRODUCTION_REFUSED"
    # Reserved for Phase 11+ with real OOS evidence — never set in Phase 8.
    PRODUCTION_CALIBRATED = "PRODUCTION_CALIBRATED"


PROTOCOL_VERSIONS: dict[WeightProtocolId, str] = {
    WeightProtocolId.PRIOR_ONLY_EQUAL_WEIGHT: "prior-equal-v1",
    WeightProtocolId.PRIOR_ONLY_SUITABILITY_PROPORTIONAL: "prior-suitability-v1",
    WeightProtocolId.INTRINSIC_VALUE_WEIGHTING: "intrinsic-weighting-v1",
    WeightProtocolId.MARKET_OUTCOME_WEIGHTING: "market-outcome-weighting-v1",
}


class WeightProtocol(BaseModel):
    """Documented weight protocol fixed before the evaluation period (SPEC §13.3.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_id: WeightProtocolId
    protocol_version: str
    target: ValuationTarget
    scoring_rule: ScoringRule
    mode: EnsembleMode
    description: str = ""
    # Artifact kind separation (SPEC §13.4)
    artifact_kind: Literal["intrinsic_value_weights", "MARKET_OUTCOME_WEIGHTING"] = (
        "intrinsic_value_weights"
    )

    @property
    def is_prior_only(self) -> bool:
        return self.mode is EnsembleMode.PRIOR_ONLY or self.protocol_id in {
            WeightProtocolId.PRIOR_ONLY_EQUAL_WEIGHT,
            WeightProtocolId.PRIOR_ONLY_SUITABILITY_PROPORTIONAL,
        }

    @property
    def is_market_outcome(self) -> bool:
        return (
            self.protocol_id is WeightProtocolId.MARKET_OUTCOME_WEIGHTING
            or self.artifact_kind == "MARKET_OUTCOME_WEIGHTING"
        )


def make_prior_equal_protocol(target: ValuationTarget) -> WeightProtocol:
    return WeightProtocol(
        protocol_id=WeightProtocolId.PRIOR_ONLY_EQUAL_WEIGHT,
        protocol_version=PROTOCOL_VERSIONS[WeightProtocolId.PRIOR_ONLY_EQUAL_WEIGHT],
        target=target,
        scoring_rule=ScoringRule.NONE_PRIOR,
        mode=EnsembleMode.PRIOR_ONLY,
        description=(
            "Exploratory equal-weight baseline (SPEC §13.3). "
            "Labeled PRIOR_ONLY — not a production calibrated ensemble."
        ),
        artifact_kind="intrinsic_value_weights",
    )


def make_intrinsic_protocol(
    target: ValuationTarget,
    *,
    scoring_rule: ScoringRule = ScoringRule.CRPS,
    calibrated: bool = False,
) -> WeightProtocol:
    """Intrinsic-value reliability weights. ``calibrated=True`` requires OOS evidence."""
    return WeightProtocol(
        protocol_id=WeightProtocolId.INTRINSIC_VALUE_WEIGHTING,
        protocol_version=PROTOCOL_VERSIONS[WeightProtocolId.INTRINSIC_VALUE_WEIGHTING],
        target=target,
        scoring_rule=scoring_rule,
        mode=(
            EnsembleMode.PRODUCTION_CALIBRATED
            if calibrated
            else EnsembleMode.PRODUCTION_REFUSED
        ),
        description=(
            "Intrinsic-value reliability weighting (SPEC §13.4). "
            "Must not reuse MARKET_OUTCOME_WEIGHTING artifacts."
        ),
        artifact_kind="intrinsic_value_weights",
    )


def make_market_outcome_protocol(
    target: ValuationTarget,
    *,
    scoring_rule: ScoringRule = ScoringRule.CRPS,
    calibrated: bool = False,
) -> WeightProtocol:
    """Market-price/return weights. Separate artifact; never reused as intrinsic."""
    return WeightProtocol(
        protocol_id=WeightProtocolId.MARKET_OUTCOME_WEIGHTING,
        protocol_version=PROTOCOL_VERSIONS[WeightProtocolId.MARKET_OUTCOME_WEIGHTING],
        target=target,
        scoring_rule=scoring_rule,
        mode=(
            EnsembleMode.PRODUCTION_CALIBRATED
            if calibrated
            else EnsembleMode.PRODUCTION_REFUSED
        ),
        description=(
            "MARKET_OUTCOME_WEIGHTING (SPEC §13.4). Trained to predict market "
            "prices/returns; must not be reused as intrinsic-value reliability weights."
        ),
        artifact_kind="MARKET_OUTCOME_WEIGHTING",
    )


__all__ = [
    "WeightProtocolId",
    "ScoringRule",
    "EnsembleMode",
    "PROTOCOL_VERSIONS",
    "WeightProtocol",
    "make_prior_equal_protocol",
    "make_intrinsic_protocol",
    "make_market_outcome_protocol",
]
