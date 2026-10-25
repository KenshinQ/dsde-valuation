"""R9: live value-rim out-dir → MethodDistribution[] for PRIOR_ONLY research wiring.

Reads single-ticket ``vms value-rim`` artifacts and builds FI-compatible
``MethodDistribution`` components for ``build_prior_only_fi_bundle(components=...)``.

Hard labels stay research PRIOR_ONLY / ENSEMBLE_UNCALIBRATED /
CALIBRATION_INSUFFICIENT / INVESTMENT_VALUE_NOT_ESTABLISHED. Never promotes to
ENSEMBLE_CALIBRATED. Not a calibrated production ensemble.

Centers (pinned):
- Track A: method_result.values.value_per_share preferred; else
  rim_distribution.ke_grid[0].vps_p50
- pb_common optional: rim_pb_roe.relative_vps when ok
- Track B: hist_n from rim_track_b.hist_pb.n; center rim_track_b.pb_center_used
  (eligible for weights only when hist_n >= MIN_HIST_PB_POINTS and center present;
  else SKIP via sanitize / ledger)

Samples still use ``samples_from_point(center)`` for this minimal slice;
``diagnostics["synthetic"]=False`` and source artifact paths are cited.
calibrate-rim is NOT a primary input.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vms.ensemble import MethodDistribution
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.prior_only_fi_bundle import (
    METHOD_RIM_TRACK_A,
    PriorOnlyFiBundleError,
    build_fi_method_components,
)
from vms.schemas.contracts import OutputBasis, ValuationTarget

LIVE_DATA_LABEL = (
    "LIVE_VALUE_RIM — research PRIOR_ONLY ingest from value-rim artifacts; "
    "not calibrated; not investment advice"
)

ARTIFACT_METHOD_RESULT = "method_result.json"
ARTIFACT_RIM_DISTRIBUTION = "rim_distribution.json"
ARTIFACT_RIM_PB_ROE = "rim_pb_roe.json"
ARTIFACT_RIM_TRACK_B = "rim_track_b.json"
ARTIFACT_SUMMARY = "value_rim_summary.json"


class FiMethodDistributionAdapterError(PriorOnlyFiBundleError):
    """Raised when live value-rim artifacts cannot yield a Track A center."""


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise FiMethodDistributionAdapterError(
            f"{path.name} must be a JSON object, got {type(raw).__name__}"
        )
    return raw


def _finite_positive(x: Any) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if f != f or abs(f) == float("inf") or f <= 0:
        return None
    return f


def _vps_from_method_result(payload: dict[str, Any] | None) -> float | None:
    if not payload:
        return None
    values = payload.get("values") or {}
    if not isinstance(values, dict):
        return None
    raw = values.get("value_per_share")
    if raw is None:
        return None
    if isinstance(raw, dict):
        for key in ("p50", "mean", "p1", "value"):
            got = _finite_positive(raw.get(key))
            if got is not None:
                return got
        return None
    return _finite_positive(raw)


def _vps_from_rim_distribution(payload: dict[str, Any] | None) -> float | None:
    if not payload:
        return None
    grid = payload.get("ke_grid") or []
    if not isinstance(grid, list) or not grid:
        return None
    cell0 = grid[0]
    if not isinstance(cell0, dict):
        return None
    return _finite_positive(cell0.get("vps_p50"))


def _pb_relative_vps(payload: dict[str, Any] | None) -> float | None:
    """Optional pb_common center from rim_pb_roe when status/ok."""
    if not payload:
        return None
    ok = payload.get("ok")
    status = str(payload.get("status") or "").upper()
    if ok is False:
        return None
    if status in {"INELIGIBLE", "UNAVAILABLE", "FAILED", "ERROR"}:
        return None
    if ok is not True and status not in {"VALID", "OK", ""}:
        return None
    return _finite_positive(payload.get("relative_vps"))


def _track_b_fields(payload: dict[str, Any] | None) -> tuple[int, float | None]:
    """Return (hist_n, pb_center_used). Missing hist → 0; missing center → None."""
    if not payload:
        return 0, None
    hist = payload.get("hist_pb") or {}
    hist_n = 0
    if isinstance(hist, dict):
        try:
            hist_n = int(hist.get("n") or 0)
        except (TypeError, ValueError):
            hist_n = 0
    center = _finite_positive(payload.get("pb_center_used"))
    return hist_n, center


def _mark_live(
    components: list[MethodDistribution],
    *,
    source_paths: list[str],
    rim_vps_source: str,
) -> list[MethodDistribution]:
    """Rewrite diagnostics: synthetic=False + cite value-rim artifact paths."""
    out: list[MethodDistribution] = []
    for c in components:
        diag = dict(c.diagnostics)
        diag["synthetic"] = False
        diag["source"] = "value_rim"
        diag["source_artifacts"] = list(source_paths)
        diag["assumption"] = "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1"
        if c.method_id == METHOD_RIM_TRACK_A:
            diag["rim_vps_source"] = rim_vps_source
        out.append(
            MethodDistribution(
                method_id=c.method_id,
                samples=c.samples,
                status=c.status,
                target=c.target,
                output_basis=c.output_basis,
                eligible=c.eligible,
                diagnostics=diag,
            )
        )
    return out


def adapt_value_rim_dir(
    value_rim_dir: Path | str,
    *,
    target: ValuationTarget = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
    basis: OutputBasis = OutputBasis.PER_SHARE,
    seed: int = 42,
    n_samples: int = 96,
) -> tuple[list[MethodDistribution], list[dict[str, Any]], dict[str, Any]]:
    """Adapt a value-rim out directory into MethodDistribution components.

    Returns ``(components, track_b_ledger, meta)``. ``meta`` includes
    ``data_label``, ``source_artifacts``, and extracted centers for stamping.
    """
    root = Path(value_rim_dir)
    if not root.is_dir():
        raise FiMethodDistributionAdapterError(
            f"value-rim directory does not exist: {root}"
        )

    mr_path = root / ARTIFACT_METHOD_RESULT
    dist_path = root / ARTIFACT_RIM_DISTRIBUTION
    pb_path = root / ARTIFACT_RIM_PB_ROE
    tb_path = root / ARTIFACT_RIM_TRACK_B
    summary_path = root / ARTIFACT_SUMMARY

    method_result = _read_json(mr_path)
    rim_distribution = _read_json(dist_path)
    pb_roe = _read_json(pb_path)
    track_b = _read_json(tb_path)
    summary = _read_json(summary_path)

    source_paths: list[str] = []
    rim_vps = _vps_from_method_result(method_result)
    rim_vps_source = ARTIFACT_METHOD_RESULT
    if rim_vps is not None:
        source_paths.append(ARTIFACT_METHOD_RESULT)
    else:
        rim_vps = _vps_from_rim_distribution(rim_distribution)
        rim_vps_source = ARTIFACT_RIM_DISTRIBUTION
        if rim_vps is not None:
            source_paths.append(ARTIFACT_RIM_DISTRIBUTION)

    if rim_vps is None:
        raise FiMethodDistributionAdapterError(
            "Track A residual_income center missing: need "
            f"{ARTIFACT_METHOD_RESULT} values.value_per_share or "
            f"{ARTIFACT_RIM_DISTRIBUTION} ke_grid[0].vps_p50"
        )

    pb_vps = _pb_relative_vps(pb_roe)
    if pb_vps is not None:
        source_paths.append(ARTIFACT_RIM_PB_ROE)

    hist_n, tb_center = _track_b_fields(track_b)
    if track_b is not None:
        source_paths.append(ARTIFACT_RIM_TRACK_B)

    # Only emit Track B component / SKIP ledger when rim_track_b.json exists.
    if track_b is None:
        track_b_exit_center = None
        track_b_hist_n = 0
        include_skip = False
    else:
        track_b_hist_n = hist_n
        track_b_exit_center = (
            tb_center if (tb_center is not None and hist_n >= MIN_HIST_PB_POINTS) else None
        )
        include_skip = True

    components, ledger = build_fi_method_components(
        rim_vps=rim_vps,
        target=target,
        basis=basis,
        seed=seed,
        n_samples=n_samples,
        pb_vps=pb_vps,
        track_b_exit_center=track_b_exit_center,
        track_b_hist_n=track_b_hist_n,
        include_track_b_skip_record=include_skip,
    )
    components = _mark_live(
        components, source_paths=source_paths, rim_vps_source=rim_vps_source
    )

    instrument_id = None
    if summary and summary.get("instrument_id"):
        instrument_id = summary.get("instrument_id")

    meta: dict[str, Any] = {
        "data_label": LIVE_DATA_LABEL,
        "source": "value_rim",
        "value_rim_dir": str(root.resolve()),
        "source_artifacts": list(source_paths),
        "rim_vps": rim_vps,
        "rim_vps_source": rim_vps_source,
        "pb_vps": pb_vps,
        "track_b_hist_n": track_b_hist_n,
        "track_b_pb_center_used": tb_center,
        "track_b_in_weights_eligible": (
            track_b is not None
            and tb_center is not None
            and hist_n >= MIN_HIST_PB_POINTS
        ),
        "min_hist_pb_points": MIN_HIST_PB_POINTS,
        "instrument_id": instrument_id,
        "assumption": "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1",
        "synthetic": False,
    }
    return components, ledger, meta


__all__ = [
    "ARTIFACT_METHOD_RESULT",
    "ARTIFACT_RIM_DISTRIBUTION",
    "ARTIFACT_RIM_PB_ROE",
    "ARTIFACT_RIM_TRACK_B",
    "FiMethodDistributionAdapterError",
    "LIVE_DATA_LABEL",
    "adapt_value_rim_dir",
]
