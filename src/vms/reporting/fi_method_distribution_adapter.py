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
- Track B PER_SHARE center: prefer rim_track_b.exit_prices.summaries[<h>].p50
  (exit_price_per_share median; first finite horizon in numeric key order).
  Optional explicit exit_vps_center / exit_price_per_share_p50 also accepted.
  ``pb_center_used`` is an own-hist **P/B multiple** kept for audit only —
  **never** fed as PER_SHARE into mixture weights. Both hist_n >= MIN_HIST_PB_POINTS
  **and** a mapped PER_SHARE center are required to enter weights; else SKIP
  (HIST_PB_BELOW_MIN or TRACK_B_CENTER_NOT_PER_SHARE / TRACK_B_EXIT_CENTER_MISSING).

Samples (R10): prefer path-level arrays persisted by value-rim
(``rim_distribution.ke_grid[0].vps_samples``,
``rim_track_b.exit_prices.summaries[<h>].exit_vps_samples``) →
``sample_generation=live_paths``, ``synthetic=false``, ``n_live_samples``.
Missing arrays → R9 compat ``samples_from_point`` stamp. Optional pb_common
may stay ``samples_from_point`` when only a point ``relative_vps`` exists.
calibrate-rim is NOT a primary input for ``adapt_value_rim_dir``.
A parallel research ingest ``adapt_calibrate_rim_forecast`` reads one
calibrate-rim forecast blob (R12); it does not change value-rim semantics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vms.ensemble import MethodDistribution
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.prior_only_fi_bundle import (
    METHOD_RIM_TRACK_A,
    METHOD_TRACK_B_EXIT,
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

SKIP_TRACK_B_CENTER_NOT_PER_SHARE = "TRACK_B_CENTER_NOT_PER_SHARE"
SKIP_TRACK_B_EXIT_CENTER_MISSING = "TRACK_B_EXIT_CENTER_MISSING"


class FiMethodDistributionAdapterError(PriorOnlyFiBundleError):
    """Raised when live value-rim artifacts cannot yield a Track A center."""


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        raw = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        raise FiMethodDistributionAdapterError(
            f"failed to read {path.name}: {e}"
        ) from e
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




def _cap_live_list(raw: Any, *, cap: int) -> list[float] | None:
    """Parse a JSON sample array into finite positive floats, capped."""
    if not isinstance(raw, (list, tuple)):
        return None
    out: list[float] = []
    for x in raw:
        got = _finite_positive(x)
        if got is None:
            continue
        out.append(got)
        if len(out) >= cap:
            break
    return out if out else None


def _live_rim_vps_samples(
    payload: dict[str, Any] | None,
    *,
    cap: int,
) -> list[float] | None:
    """Primary ke cell ``vps_samples`` from rim_distribution.json (R10)."""
    if not payload:
        return None
    grid = payload.get("ke_grid") or []
    if not isinstance(grid, list) or not grid:
        return None
    cell0 = grid[0]
    if not isinstance(cell0, dict):
        return None
    return _cap_live_list(cell0.get("vps_samples"), cap=cap)


def _horizon_from_exit_source(exit_vps_source: str | None) -> str | None:
    """Parse ``exit_prices.summaries[<h>].p50`` → ``<h>`` key."""
    if not exit_vps_source:
        return None
    marker = "exit_prices.summaries["
    if not exit_vps_source.startswith(marker):
        return None
    rest = exit_vps_source[len(marker) :]
    if "]" not in rest:
        return None
    return rest.split("]", 1)[0]


def _live_track_b_exit_samples(
    payload: dict[str, Any] | None,
    *,
    exit_vps_source: str | None,
    cap: int,
) -> list[float] | None:
    """Capped ``exit_vps_samples`` from the **center** horizon only (SF1).

    When the center horizon (parsed from ``exit_vps_source``) lacks samples,
    return None so Track B falls back to ``samples_from_point`` — never steal
    samples from a different horizon.
    """
    if not payload:
        return None
    exit_prices = payload.get("exit_prices")
    if not isinstance(exit_prices, dict):
        return None
    summaries = exit_prices.get("summaries")
    if not isinstance(summaries, dict) or not summaries:
        return None
    preferred = _horizon_from_exit_source(exit_vps_source)
    if preferred is None or preferred not in summaries:
        # No mapped center horizon → no live samples (compat fallback upstream).
        return None
    cell = summaries[preferred]
    if not isinstance(cell, dict):
        return None
    return _cap_live_list(cell.get("exit_vps_samples"), cap=cap)

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


def _horizon_sort_key(key: Any) -> tuple[int, float | str]:
    try:
        return (0, float(key))
    except (TypeError, ValueError):
        return (1, str(key))


def _track_b_exit_vps(
    payload: dict[str, Any] | None,
) -> tuple[float | None, str | None]:
    """PER_SHARE exit center from live Track B artifacts.

    Preference order:
    1. Explicit ``exit_vps_center`` / ``exit_price_per_share_p50`` on the payload
    2. ``exit_prices.summaries[<horizon>].p50`` (exit_price_per_share median);
       first finite horizon in numeric key order

    Never returns ``pb_center_used`` (that is a P/B multiple, not PER_SHARE).
    """
    if not payload:
        return None, None
    for key in ("exit_vps_center", "exit_price_per_share_p50"):
        got = _finite_positive(payload.get(key))
        if got is not None:
            return got, key

    exit_prices = payload.get("exit_prices")
    if not isinstance(exit_prices, dict):
        return None, None
    summaries = exit_prices.get("summaries")
    if not isinstance(summaries, dict) or not summaries:
        return None, None
    for hk in sorted(summaries.keys(), key=_horizon_sort_key):
        cell = summaries[hk]
        if not isinstance(cell, dict):
            continue
        got = _finite_positive(cell.get("p50"))
        if got is not None:
            return got, f"exit_prices.summaries[{hk}].p50"
    return None, None


def _track_b_fields(
    payload: dict[str, Any] | None,
) -> tuple[int, float | None, float | None, str | None]:
    """Return (hist_n, pb_center_used_multiple, exit_vps_center, exit_vps_source).

    ``pb_center_used`` is the own-hist P/B multiple (audit only).
    ``exit_vps_center`` is the PER_SHARE center eligible for mixture weights.
    """
    if not payload:
        return 0, None, None, None
    hist = payload.get("hist_pb") or {}
    hist_n = 0
    if isinstance(hist, dict):
        try:
            hist_n = int(hist.get("n") or 0)
        except (TypeError, ValueError):
            hist_n = 0
    pb_multiple = _finite_positive(payload.get("pb_center_used"))
    exit_vps, exit_src = _track_b_exit_vps(payload)
    return hist_n, pb_multiple, exit_vps, exit_src


def _rewrite_track_b_skip_reason(
    components: list[MethodDistribution],
    ledger: list[dict[str, Any]],
    *,
    skip_reason: str,
    pb_center_used: float | None,
) -> tuple[list[MethodDistribution], list[dict[str, Any]]]:
    """Stamp honest SKIP reason when hist gate passed but center is not PER_SHARE."""
    new_comps: list[MethodDistribution] = []
    for c in components:
        if c.method_id != METHOD_TRACK_B_EXIT or c.eligible:
            new_comps.append(c)
            continue
        diag = dict(c.diagnostics)
        diag["skip_reason"] = skip_reason
        if pb_center_used is not None:
            diag["track_b_pb_center_used"] = float(pb_center_used)
            diag["track_b_pb_center_is_multiple"] = True
        new_comps.append(
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
    new_ledger: list[dict[str, Any]] = []
    for entry in ledger:
        e = dict(entry)
        if e.get("method_id") == METHOD_TRACK_B_EXIT and e.get("status") == "SKIP":
            e["skip_reason"] = skip_reason
            if pb_center_used is not None:
                e["track_b_pb_center_used"] = float(pb_center_used)
        new_ledger.append(e)
    return new_comps, new_ledger


def _mark_live(
    components: list[MethodDistribution],
    *,
    source_paths: list[str],
    rim_vps_source: str,
    track_b_meta: dict[str, Any] | None = None,
    primary_assumption: str = "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1",
) -> list[MethodDistribution]:
    """Rewrite diagnostics: synthetic=False + cite value-rim artifact paths.

    Preserves per-component ``sample_generation`` / ``n_live_samples`` from
    ``build_fi_method_components`` when live path samples were supplied (R10).
    """
    out: list[MethodDistribution] = []
    for c in components:
        diag = dict(c.diagnostics)
        gen = diag.get("sample_generation") or "samples_from_point"
        if gen not in {"live_paths", "samples_from_point"}:
            gen = "samples_from_point"
        diag["sample_generation"] = gen
        # Live ingest is never synthetic demo data, even when samples_from_point
        # is the R9 compat fallback around a live center.
        diag["synthetic"] = False
        diag["source"] = "value_rim"
        diag["source_artifacts"] = list(source_paths)
        diag["assumption"] = primary_assumption
        if c.method_id == METHOD_RIM_TRACK_A:
            diag["rim_vps_source"] = rim_vps_source
        if c.method_id == METHOD_TRACK_B_EXIT and track_b_meta:
            if track_b_meta.get("pb_center_used") is not None:
                diag["track_b_pb_center_used"] = track_b_meta["pb_center_used"]
                diag["track_b_pb_center_is_multiple"] = True
            if track_b_meta.get("exit_vps_center") is not None:
                diag["track_b_exit_vps_center"] = track_b_meta["exit_vps_center"]
            if track_b_meta.get("exit_vps_source"):
                diag["track_b_exit_vps_source"] = track_b_meta["exit_vps_source"]
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

    hist_n, pb_multiple, exit_vps, exit_vps_source = _track_b_fields(track_b)
    if track_b is not None:
        source_paths.append(ARTIFACT_RIM_TRACK_B)

    # Only emit Track B component / SKIP ledger when rim_track_b.json exists.
    # Never pass raw pb_center_used (P/B multiple) as PER_SHARE center.
    if track_b is None:
        track_b_exit_center = None
        track_b_hist_n = 0
        include_skip = False
        force_not_per_share_skip = False
    else:
        track_b_hist_n = hist_n
        hist_ok = hist_n >= MIN_HIST_PB_POINTS
        if hist_ok and exit_vps is not None:
            track_b_exit_center = exit_vps
            force_not_per_share_skip = False
        else:
            track_b_exit_center = None
            # hist gate passed but only a PB multiple (or nothing) was available
            force_not_per_share_skip = hist_ok and exit_vps is None
        include_skip = True

    rim_live = _live_rim_vps_samples(rim_distribution, cap=n_samples)
    tb_live = (
        _live_track_b_exit_samples(
            track_b, exit_vps_source=exit_vps_source, cap=n_samples
        )
        if track_b_exit_center is not None
        else None
    )
    # Optional pb_common: only a point relative_vps today → keep samples_from_point.
    pb_live = None

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
        rim_samples=rim_live,
        pb_samples=pb_live,
        track_b_samples=tb_live,
    )

    if force_not_per_share_skip:
        # Prefer TRACK_B_CENTER_NOT_PER_SHARE when a PB multiple was present
        # (unit mismatch) over generic TRACK_B_EXIT_CENTER_MISSING.
        reason = (
            SKIP_TRACK_B_CENTER_NOT_PER_SHARE
            if pb_multiple is not None
            else SKIP_TRACK_B_EXIT_CENTER_MISSING
        )
        components, ledger = _rewrite_track_b_skip_reason(
            components,
            ledger,
            skip_reason=reason,
            pb_center_used=pb_multiple,
        )

    track_b_meta = {
        "pb_center_used": float(pb_multiple) if pb_multiple is not None else None,
        "exit_vps_center": float(exit_vps) if exit_vps is not None else None,
        "exit_vps_source": exit_vps_source,
    }
    any_live = any(
        c.diagnostics.get("sample_generation") == "live_paths" for c in components
    )
    primary_assumption = (
        "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1"
        if any_live
        else "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1"
    )
    components = _mark_live(
        components,
        source_paths=source_paths,
        rim_vps_source=rim_vps_source,
        track_b_meta=track_b_meta if track_b is not None else None,
        primary_assumption=primary_assumption,
    )

    instrument_id = None
    if summary and summary.get("instrument_id"):
        instrument_id = summary.get("instrument_id")

    in_weights_eligible = (
        track_b is not None
        and exit_vps is not None
        and hist_n >= MIN_HIST_PB_POINTS
    )
    sample_generation = "live_paths" if any_live else "samples_from_point"
    meta: dict[str, Any] = {
        "data_label": LIVE_DATA_LABEL,
        "source": "value_rim",
        "value_rim_dir": str(root.resolve()),
        "source_artifacts": list(source_paths),
        "rim_vps": rim_vps,
        "rim_vps_source": rim_vps_source,
        "pb_vps": pb_vps,
        "track_b_hist_n": track_b_hist_n,
        "track_b_pb_center_used": (
            float(pb_multiple) if pb_multiple is not None else None
        ),
        "track_b_exit_vps_center": (
            float(exit_vps) if exit_vps is not None else None
        ),
        "track_b_exit_vps_source": exit_vps_source,
        "track_b_in_weights_eligible": in_weights_eligible,
        "min_hist_pb_points": MIN_HIST_PB_POINTS,
        "instrument_id": instrument_id,
        "assumption": primary_assumption,
        "synthetic": False,
        "sample_generation": sample_generation,
        "rim_live_samples": bool(rim_live),
        "track_b_live_samples": bool(tb_live),
        "n_rim_live_samples": (len(rim_live) if rim_live else 0),
        "n_track_b_live_samples": (len(tb_live) if tb_live else 0),
    }
    return components, ledger, meta




# ---------------------------------------------------------------------------
# calibrate-rim forecast blob → MethodDistribution (research PRIOR_ONLY)
# ---------------------------------------------------------------------------

CALIBRATE_RIM_DATA_LABEL = (
    "LIVE_CALIBRATE_RIM_FORECAST — research PRIOR_ONLY ingest from calibrate-rim "
    "forecast blob; not calibrated; not investment advice"
)

CALIBRATE_RIM_ASSUMPTION = "ENSEMBLE-PRIOR-ONLY-FI-CALIBRATE-RIM-MD-v1"


def _payload_from_path_or_dict(
    path_or_payload: Path | str | dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Return (payload, source_path_str). path_or_payload may be a dict already."""
    if isinstance(path_or_payload, dict):
        return path_or_payload, None
    path = Path(path_or_payload)
    if not path.is_file():
        raise FiMethodDistributionAdapterError(
            f"calibrate-rim forecast file does not exist: {path}"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        raise FiMethodDistributionAdapterError(
            f"failed to read calibrate-rim forecast {path.name}: {e}"
        ) from e
    if not isinstance(raw, dict):
        raise FiMethodDistributionAdapterError(
            f"calibrate-rim forecast must be a JSON object, got {type(raw).__name__}"
        )
    return raw, str(path.resolve())


def _track_a_from_calibrate_rim(
    payload: dict[str, Any],
) -> tuple[float, str]:
    """Track A PER_SHARE center from forecast blob.

    Preference:
    1. forecasts.intrinsic_value (status==VALID, finite positive point)
    2. baselines.central_rim.vps (finite positive)
    """
    forecasts = payload.get("forecasts") or {}
    if isinstance(forecasts, dict):
        iv = forecasts.get("intrinsic_value") or {}
        if isinstance(iv, dict):
            status = str(iv.get("status") or "").upper()
            if status == "VALID":
                got = _finite_positive(iv.get("point"))
                if got is not None:
                    return got, "forecasts.intrinsic_value.point"

    baselines = payload.get("baselines") or {}
    if isinstance(baselines, dict):
        central = baselines.get("central_rim") or {}
        if isinstance(central, dict):
            got = _finite_positive(central.get("vps"))
            if got is not None:
                return got, "baselines.central_rim.vps"

    raise FiMethodDistributionAdapterError(
        "Track A residual_income center missing: need "
        "forecasts.intrinsic_value (status=VALID, finite positive point) or "
        "baselines.central_rim.vps"
    )


def _calibrate_rim_track_b_fields(
    track_b: dict[str, Any] | None,
) -> tuple[int, float | None, str | None, str | None]:
    """Return (hist_n, median_pb_multiple, status, skip_reason).

    ``median_pb`` is an own-hist P/B multiple (audit only) — never PER_SHARE.
    """
    if not track_b or not isinstance(track_b, dict):
        return 0, None, None, None
    try:
        hist_n = int(track_b.get("hist_n") or 0)
    except (TypeError, ValueError):
        hist_n = 0
    median_pb = _finite_positive(track_b.get("median_pb"))
    status = track_b.get("status")
    status_s = str(status) if status is not None else None
    skip_reason = track_b.get("skip_reason")
    skip_s = str(skip_reason) if skip_reason else None
    return hist_n, median_pb, status_s, skip_s


def _mark_calibrate_rim(
    components: list[MethodDistribution],
    *,
    source_path: str | None,
    rim_vps_source: str,
    track_b_meta: dict[str, Any] | None = None,
) -> list[MethodDistribution]:
    """Rewrite diagnostics: synthetic=False + cite calibrate-rim blob."""
    out: list[MethodDistribution] = []
    cite = [source_path] if source_path else []
    for c in components:
        diag = dict(c.diagnostics)
        diag["sample_generation"] = "samples_from_point"
        diag["synthetic"] = False
        diag["source"] = "calibrate_rim"
        if cite:
            diag["source_artifacts"] = list(cite)
        diag["assumption"] = CALIBRATE_RIM_ASSUMPTION
        if c.method_id == METHOD_RIM_TRACK_A:
            diag["rim_vps_source"] = rim_vps_source
        if c.method_id == METHOD_TRACK_B_EXIT and track_b_meta:
            if track_b_meta.get("pb_center_used") is not None:
                diag["track_b_pb_center_used"] = track_b_meta["pb_center_used"]
                diag["track_b_pb_center_is_multiple"] = True
            if track_b_meta.get("blob_status") is not None:
                diag["track_b_blob_status"] = track_b_meta["blob_status"]
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


def resolve_calibrate_rim_forecast_path(
    calibrate_rim_dir: Path | str,
    *,
    instrument_id: str,
    origin_as_of: str,
) -> Path:
    """Resolve ``DIR/forecasts/<ID>/<DATE>_h*.json`` with fail-closed disambiguation.

    ``origin_as_of`` is a calendar date (``YYYY-MM-DD``); matches the filename
    prefix. Zero matches or multiple horizon files for the same date → error
    (never silently pick "latest").
    """
    root = Path(calibrate_rim_dir)
    if not root.is_dir():
        raise FiMethodDistributionAdapterError(
            f"calibrate-rim directory does not exist: {root}"
        )
    date_key = str(origin_as_of).strip()
    if "T" in date_key:
        date_key = date_key.split("T", 1)[0]
    # Accept full ISO; normalize to YYYY-MM-DD for filename match.
    if len(date_key) >= 10:
        date_key = date_key[:10]
    forecast_dir = root / "forecasts" / instrument_id
    if not forecast_dir.is_dir():
        raise FiMethodDistributionAdapterError(
            f"no forecasts directory for instrument {instrument_id!r} under {root}"
        )
    matches = sorted(forecast_dir.glob(f"{date_key}_h*.json"))
    if not matches:
        raise FiMethodDistributionAdapterError(
            f"no calibrate-rim forecast matching instrument={instrument_id!r} "
            f"origin_as_of={date_key!r} under {forecast_dir}"
        )
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise FiMethodDistributionAdapterError(
            f"ambiguous calibrate-rim forecast for instrument={instrument_id!r} "
            f"origin_as_of={date_key!r}: {names} "
            "(pass --from-calibrate-rim-forecast PATH to select one)"
        )
    return matches[0]


def adapt_calibrate_rim_forecast(
    path_or_payload: Path | str | dict[str, Any],
    *,
    target: ValuationTarget = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
    basis: OutputBasis = OutputBasis.PER_SHARE,
    seed: int = 42,
    n_samples: int = 96,
) -> tuple[list[MethodDistribution], list[dict[str, Any]], dict[str, Any]]:
    """Adapt one calibrate-rim forecast JSON into MethodDistribution components.

    Returns ``(components, track_b_ledger, meta)``. Research PRIOR_ONLY only —
    never ENSEMBLE_CALIBRATED. This slice never produces pb_common and never
    puts Track B into mixture weights (blob has no PER_SHARE exit VPS;
    ``median_pb`` is audit-only).
    """
    payload, source_path = _payload_from_path_or_dict(path_or_payload)

    rim_vps, rim_vps_source = _track_a_from_calibrate_rim(payload)

    raw_tb = payload.get("track_b")
    track_b = raw_tb if isinstance(raw_tb, dict) else None
    hist_n, median_pb, tb_status, tb_skip = _calibrate_rim_track_b_fields(track_b)

    if track_b is None:
        track_b_exit_center = None
        track_b_hist_n = 0
        include_skip = False
        force_not_per_share_skip = False
        force_hist_skip_reason: str | None = None
    else:
        track_b_hist_n = hist_n
        hist_ok = hist_n >= MIN_HIST_PB_POINTS
        # This slice has no exit VPS → never enter weights.
        track_b_exit_center = None
        include_skip = True
        if hist_ok:
            force_not_per_share_skip = True
            force_hist_skip_reason = None
        else:
            force_not_per_share_skip = False
            # Preserve explicit SKIP reason; never default NOT_ASSESSED → HIST_PB_BELOW_MIN.
            status_u = (tb_status or "").upper()
            if status_u == "NOT_ASSESSED":
                force_hist_skip_reason = tb_skip or "NOT_ASSESSED"
            elif tb_skip:
                force_hist_skip_reason = tb_skip
            else:
                force_hist_skip_reason = "HIST_PB_BELOW_MIN"

    components, ledger = build_fi_method_components(
        rim_vps=rim_vps,
        target=target,
        basis=basis,
        seed=seed,
        n_samples=n_samples,
        pb_vps=None,  # no relative_vps / pb_common on calibrate-rim blob
        track_b_exit_center=track_b_exit_center,
        track_b_hist_n=track_b_hist_n,
        include_track_b_skip_record=include_skip,
        rim_samples=None,
        pb_samples=None,
        track_b_samples=None,
    )

    if force_not_per_share_skip:
        components, ledger = _rewrite_track_b_skip_reason(
            components,
            ledger,
            skip_reason=SKIP_TRACK_B_CENTER_NOT_PER_SHARE,
            pb_center_used=median_pb,
        )
    elif force_hist_skip_reason is not None:
        components, ledger = _rewrite_track_b_skip_reason(
            components,
            ledger,
            skip_reason=force_hist_skip_reason,
            pb_center_used=median_pb,
        )

    track_b_meta = None
    if track_b is not None:
        track_b_meta = {
            "pb_center_used": float(median_pb) if median_pb is not None else None,
            "blob_status": tb_status,
        }

    components = _mark_calibrate_rim(
        components,
        source_path=source_path,
        rim_vps_source=rim_vps_source,
        track_b_meta=track_b_meta,
    )

    meta: dict[str, Any] = {
        "data_label": CALIBRATE_RIM_DATA_LABEL,
        "source": "calibrate_rim",
        "source_forecast": source_path,
        "source_artifacts": [source_path] if source_path else [],
        "rim_vps": rim_vps,
        "rim_vps_source": rim_vps_source,
        "pb_vps": None,
        "track_b_hist_n": track_b_hist_n if track_b is not None else 0,
        "track_b_pb_center_used": (
            float(median_pb) if median_pb is not None else None
        ),
        "track_b_exit_vps_center": None,
        "track_b_exit_vps_source": None,
        "track_b_in_weights_eligible": False,
        "track_b_blob_status": tb_status,
        "min_hist_pb_points": MIN_HIST_PB_POINTS,
        "instrument_id": payload.get("instrument_id"),
        "origin_as_of": payload.get("origin_as_of"),
        "horizon_years": payload.get("horizon_years"),
        "assumption": CALIBRATE_RIM_ASSUMPTION,
        "synthetic": False,
        "sample_generation": "samples_from_point",
        "pit_complete": payload.get("pit_complete"),
    }
    return components, ledger, meta

__all__ = [
    "ARTIFACT_METHOD_RESULT",
    "ARTIFACT_RIM_DISTRIBUTION",
    "ARTIFACT_RIM_PB_ROE",
    "ARTIFACT_RIM_TRACK_B",
    "CALIBRATE_RIM_ASSUMPTION",
    "CALIBRATE_RIM_DATA_LABEL",
    "FiMethodDistributionAdapterError",
    "LIVE_DATA_LABEL",
    "SKIP_TRACK_B_CENTER_NOT_PER_SHARE",
    "adapt_calibrate_rim_forecast",
    "adapt_value_rim_dir",
    "resolve_calibrate_rim_forecast_path",
]
