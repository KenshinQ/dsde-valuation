"""Rule-based economic-profile classifier (SPEC §7).

Produces a ProfileReport with rule-ID traceability. Low confidence is visible;
the classifier does not silently hard-class when evidence is weak or conflicting.
"""

from __future__ import annotations

from collections import defaultdict

from vms.profiles.features import ProfileFeatureBundle
from vms.profiles.overrides import OverrideCatalog, find_override
from vms.profiles.report import ManualOverrideStatus, ProfileReport, RuleHitRecord
from vms.profiles.rules import RULES_VERSION, evaluate_rules
from vms.schemas.contracts import ProfileFlag, ProfileLabel

CLASSIFIER_VERSION = "vms-profile-classifier-0.2.phase2"

# Soft thresholds (versioned with CLASSIFIER_VERSION)
_MIN_CONFIDENT_SCORE = 2.5
_CONFLICT_MARGIN = 0.85  # if runner-up within this fraction of top → conflict
_LOW_CONF_THRESHOLD = 0.45


def _scores(hits) -> dict[ProfileLabel, float]:
    s: dict[ProfileLabel, float] = defaultdict(float)
    for h in hits:
        if h.profile is not None:
            s[h.profile] += h.weight
    return dict(s)


def _probs(scores: dict[ProfileLabel, float]) -> dict[str, float]:
    if not scores:
        return {ProfileLabel.HYBRID_OR_UNCLEAR.value: 1.0}
    # Softmax-like on positive scores only
    exps = {k: __import__("math").exp(min(v, 20.0)) for k, v in scores.items() if v > 0}
    if not exps:
        return {ProfileLabel.HYBRID_OR_UNCLEAR.value: 1.0}
    z = sum(exps.values())
    return {k.value: v / z for k, v in exps.items()}


def _to_records(hits) -> list[RuleHitRecord]:
    return [
        RuleHitRecord(
            rule_id=h.rule_id, profile=h.profile, flag=h.flag, weight=h.weight,
            detail=h.detail, feature_refs=list(h.feature_refs),
        )
        for h in hits
    ]


def classify_profile(
    features: ProfileFeatureBundle,
    *,
    overrides: OverrideCatalog | None = None,
) -> ProfileReport:
    """Classify economic profile from features; apply recorded manual override if present."""
    profile_hits, flag_hits = evaluate_rules(features)
    scores = _scores(profile_hits)
    missing = features.missing_fields()
    conflicts: list[str] = []

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0].value))
    if not ranked:
        primary = ProfileLabel.HYBRID_OR_UNCLEAR
        confidence = 0.15 if missing else 0.25
        low = True
        notes = "no profile rule fired; returning HYBRID_OR_UNCLEAR with low confidence"
    else:
        top_label, top_score = ranked[0]
        runner = ranked[1] if len(ranked) > 1 else None
        # Industry-aux alone: if top evidence is only aux-weight (<1.0) and no other support → low conf
        aux_only = top_score < _MIN_CONFIDENT_SCORE
        if runner and runner[1] >= top_score * _CONFLICT_MARGIN and runner[0] != top_label:
            conflicts.append(
                f"{top_label.value} score={top_score:.2f} vs {runner[0].value} score={runner[1]:.2f}"
            )
            primary = ProfileLabel.HYBRID_OR_UNCLEAR
            confidence = min(0.4, top_score / (top_score + runner[1] + 1e-9))
            low = True
            notes = "conflicting profile signals; not silently hard-classed"
        elif aux_only:
            primary = top_label
            confidence = min(0.44, top_score / (_MIN_CONFIDENT_SCORE + 1.0))
            low = True
            notes = f"top profile {top_label.value} score={top_score:.2f} below confident threshold"
        else:
            primary = top_label
            # Map score to [0.45, 0.95]
            confidence = min(0.95, 0.45 + 0.1 * top_score)
            low = confidence < _LOW_CONF_THRESHOLD or bool(missing and top_score < 4.0)
            notes = f"primary={primary.value} score={top_score:.2f}"
            if missing and low:
                notes += f"; missing core fields {missing}"

    flags: list[ProfileFlag] = []
    seen: set[ProfileFlag] = set()
    for h in flag_hits:
        if h.flag is not None and h.flag not in seen:
            flags.append(h.flag)
            seen.add(h.flag)

    override, ov_ver = find_override(overrides, instrument_id=features.instrument_id, as_of=features.as_of)
    ov_status = ManualOverrideStatus(applied=False)
    if override is not None:
        ov_status = ManualOverrideStatus(
            applied=True,
            override_version=ov_ver,
            reason=override.reason,
            overridden_primary=primary,
            source_path=None,
        )
        primary = override.primary_profile
        if override.flags:
            for fl in override.flags:
                if fl not in seen:
                    flags.append(fl)
                    seen.add(fl)
        # Override is explicit; confidence reflects that it is human-set, not model certainty
        confidence = max(confidence, 0.7)
        low = False
        notes = f"manual override applied: {override.reason} (was {ov_status.overridden_primary})"

    if features.low_data_quality and ProfileFlag.LOW_DATA_QUALITY not in seen:
        flags.append(ProfileFlag.LOW_DATA_QUALITY)
        low = True

    probs = _probs(scores)
    # Ensure primary appears in probabilities map for consumers
    if primary.value not in probs and primary is not ProfileLabel.HYBRID_OR_UNCLEAR:
        probs = {**probs, primary.value: max(probs.values(), default=0.0)}

    return ProfileReport(
        instrument_id=features.instrument_id,
        as_of=features.as_of,
        classifier_version=CLASSIFIER_VERSION,
        rules_version=RULES_VERSION,
        primary_profile=primary,
        flags=flags,
        confidence=round(confidence, 4),
        low_confidence=low,
        profile_scores={k.value: round(v, 4) for k, v in scores.items()},
        profile_probabilities={k: round(v, 4) for k, v in probs.items()},
        rule_hits=_to_records(profile_hits),
        flag_hits=_to_records(flag_hits),
        conflicting_signals=conflicts,
        missing_fields=missing,
        feature_values=features.feature_values(),
        manual_override=ov_status,
        notes=notes,
    )
