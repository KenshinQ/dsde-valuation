"""PASS-claim plumbing (EVAL-CALIBRATION-PASS-CLAIM-PROTOCOL-v1).

Plumbing ≠ evidence. Without a validated artifact, calibration stays
CALIBRATION_INSUFFICIENT. A valid artifact alone never invents OOS rows:
``n_unbiased`` must still meet MIN_UNBIASED_FOR_PASS.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROTOCOL_ID = "EVAL-CALIBRATION-PASS-CLAIM-PROTOCOL-v1"
MIN_UNBIASED_FOR_PASS = 5

# data_label substrings that forbid PASS-claim authorization (case-insensitive)
_FORBIDDEN_LABEL_MARKERS = ("SYNTHETIC",)


class PassClaimArtifactError(ValueError):
    """Illegal, incomplete, or synthetic pass-claim artifact (fail-closed)."""


@dataclass(frozen=True)
class PassClaimDecision:
    authorized: bool
    reason: str
    protocol_id: str | None = None
    artifact_path: str | None = None
    artifact_universe_data_label: str | None = None
    artifact_n_unbiased: int | None = None
    run_data_label: str | None = None
    run_n_unbiased: int | None = None
    pit_incomplete_excluded: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_artifact(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PassClaimArtifactError(f"pass-claim artifact not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise PassClaimArtifactError(f"pass-claim artifact unreadable: {path}: {e}") from e
    suffix = path.suffix.lower()
    try:
        if suffix in (".yaml", ".yml"):
            import yaml  # type: ignore

            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
    except Exception as e:  # noqa: BLE001 — fail-closed on any parse error
        raise PassClaimArtifactError(f"pass-claim artifact parse failed: {path}: {e}") from e
    if not isinstance(data, dict):
        raise PassClaimArtifactError(
            f"pass-claim artifact must be a JSON/YAML object, got {type(data).__name__}"
        )
    return data


def validate_pass_claim_artifact(data: dict[str, Any]) -> dict[str, Any]:
    """Validate artifact structure. Raises PassClaimArtifactError on any defect."""
    missing = [
        k
        for k in ("protocol_id", "universe_data_label", "n_unbiased", "pit_incomplete_excluded")
        if k not in data
    ]
    if missing:
        raise PassClaimArtifactError(
            f"pass-claim artifact incomplete; missing fields: {sorted(missing)}"
        )
    protocol = data.get("protocol_id")
    if protocol != PROTOCOL_ID:
        raise PassClaimArtifactError(
            f"pass-claim protocol_id must be {PROTOCOL_ID!r}, got {protocol!r}"
        )
    label = data.get("universe_data_label")
    if not isinstance(label, str) or not label.strip():
        raise PassClaimArtifactError("pass-claim universe_data_label must be a non-empty string")
    upper = label.upper()
    for marker in _FORBIDDEN_LABEL_MARKERS:
        if marker in upper:
            raise PassClaimArtifactError(
                f"pass-claim refuses synthetic universe_data_label={label!r}"
            )
    n = data.get("n_unbiased")
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise PassClaimArtifactError(
            f"pass-claim n_unbiased must be a non-negative int, got {n!r}"
        )
    pit = data.get("pit_incomplete_excluded")
    if pit is not True:
        raise PassClaimArtifactError(
            "pass-claim requires pit_incomplete_excluded=true (fail-closed)"
        )
    return data


def resolve_pass_claim(
    artifact: str | Path | None,
    *,
    run_data_label: str,
    run_n_unbiased: int,
) -> PassClaimDecision:
    """Resolve whether PASS is authorized for this run.

    No path → not authorized (NO_ARTIFACT).
    Illegal/synthetic/incomplete → raises PassClaimArtifactError.
    Valid structure but run/artifact n_unbiased < MIN → not authorized
    (INSUFFICIENT_N_UNBIASED) — plumbing does not replace evidence.
    """
    if artifact is None or str(artifact).strip() == "":
        return PassClaimDecision(
            authorized=False,
            reason="NO_ARTIFACT",
            run_data_label=run_data_label,
            run_n_unbiased=int(run_n_unbiased),
        )

    path = Path(artifact)
    raw = validate_pass_claim_artifact(_load_artifact(path))

    # Run label must also be non-synthetic
    run_upper = (run_data_label or "").upper()
    for marker in _FORBIDDEN_LABEL_MARKERS:
        if marker in run_upper:
            raise PassClaimArtifactError(
                f"pass-claim refuses synthetic run data_label={run_data_label!r}"
            )

    art_n = int(raw["n_unbiased"])
    art_label = str(raw["universe_data_label"])
    # Artifact label should be compatible with run (exact or shared non-synthetic token)
    if art_label.upper() != run_upper and art_label.upper() not in run_upper and run_upper not in art_label.upper():
        # Soft compatibility: require artifact label appears in run label or vice versa;
        # otherwise fail-closed on mismatch.
        raise PassClaimArtifactError(
            f"pass-claim universe_data_label={art_label!r} mismatches run "
            f"data_label={run_data_label!r}"
        )

    effective_n = min(art_n, int(run_n_unbiased))
    if effective_n < MIN_UNBIASED_FOR_PASS:
        return PassClaimDecision(
            authorized=False,
            reason="INSUFFICIENT_N_UNBIASED",
            protocol_id=PROTOCOL_ID,
            artifact_path=str(path),
            artifact_universe_data_label=art_label,
            artifact_n_unbiased=art_n,
            run_data_label=run_data_label,
            run_n_unbiased=int(run_n_unbiased),
            pit_incomplete_excluded=True,
        )

    return PassClaimDecision(
        authorized=True,
        reason="AUTHORIZED",
        protocol_id=PROTOCOL_ID,
        artifact_path=str(path),
        artifact_universe_data_label=art_label,
        artifact_n_unbiased=art_n,
        run_data_label=run_data_label,
        run_n_unbiased=int(run_n_unbiased),
        pit_incomplete_excluded=True,
    )


def gate_calibration_ok(
    calibration_ok: bool | None,
    *,
    pass_claim: PassClaimDecision,
) -> bool | None:
    """Allow True only when pass-claim is authorized; else force None (INSUFFICIENT)."""
    if calibration_ok is True and not pass_claim.authorized:
        return None
    if calibration_ok is True and pass_claim.authorized:
        return True
    return calibration_ok


__all__ = [
    "MIN_UNBIASED_FOR_PASS",
    "PROTOCOL_ID",
    "PassClaimArtifactError",
    "PassClaimDecision",
    "gate_calibration_ok",
    "resolve_pass_claim",
    "validate_pass_claim_artifact",
]
