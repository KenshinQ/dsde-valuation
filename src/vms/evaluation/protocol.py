"""Chronological walk-forward protocol helpers (SPEC §17.1, Phase 11).

Random row-level time-series splits are prohibited. Ensemble weights and
thresholds that feed evaluation must be frozen before the test window
(SPEC §17.4 / §21.3).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from vms.data.io import LoadResult
from vms.evaluation.errors import RandomSplitProhibitedError
from vms.quality.report import assess
from vms.reporting.metadata import sha256_of

SplitMode = Literal["chronological"]
ALLOWED_SPLIT_MODES: tuple[str, ...] = ("chronological",)


def require_chronological(split_mode: str) -> None:
    if split_mode not in ALLOWED_SPLIT_MODES:
        raise RandomSplitProhibitedError(split_mode)


def enumerate_fy_origins(
    load: LoadResult,
    *,
    instrument_id: str,
    start: date,
    end: date,
    min_history_years: int = 3,
) -> list[tuple[int, datetime]]:
    """Return (fy_year, origin_as_of) chronologically for FY revenue first-publication times in [start, end].

    origin_as_of = first published_at of FY revenue for that year (when FY became known).
    Requires at least ``min_history_years`` prior FYs visible in the full load for training.
    """
    fins = [
        f
        for f in load.financial
        if f.instrument_id == instrument_id
        and f.field_name == "revenue"
        and f.period_end.month == 12
        and f.period_end.day == 31
        and f.value is not None
    ]
    by_year: dict[int, datetime] = {}
    for f in fins:
        y = f.period_end.year
        first = f.published_at
        if first is None:
            continue
        if y not in by_year or first < by_year[y]:
            by_year[y] = first
    years = sorted(by_year)
    out: list[tuple[int, datetime]] = []
    for y in years:
        origin = by_year[y]
        if origin.date() < start or origin.date() > end:
            continue
        prior = [yy for yy in years if yy < y]
        if len(prior) < min_history_years:
            continue
        out.append((y, origin))
    return out  # already chronological by year order


def reconstruct_pit(load: LoadResult, *, instrument_id: str, as_of: datetime, cfg_quality):
    """Rebuild the information set available at ``as_of`` (past-only)."""
    return assess(
        load,
        instrument_id=instrument_id,
        as_of=as_of,
        cfg=cfg_quality,
        mode="exploratory",
        override_reason="phase11_walk_forward_origin",
    )


def freeze_weights_before_test(
    *,
    weights: dict[str, float],
    thresholds: dict[str, Any] | None,
    test_window_start: date,
    out_dir: str | Path,
) -> dict[str, Any]:
    """Persist ensemble weights/thresholds BEFORE the test window (SPEC §17.4 / §21.3).

    Returns a freeze record with content hash. Callers must refuse to mutate the
    freeze file after ``test_window_start`` when scoring that window.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_kind": "FrozenEvalWeights",
        "test_window_start": test_window_start.isoformat(),
        "weights": {k: float(v) for k, v in sorted(weights.items())},
        "thresholds": thresholds or {},
        "frozen_before_test": True,
        "note": (
            "Weights/thresholds frozen before test window. Mutating after "
            "test_window_start invalidates calibration claims (SPEC §21.3)."
        ),
    }
    payload["content_hash"] = sha256_of(payload)[:16]
    path = out / "frozen_weights.json"
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {**payload, "path": str(path)}


def assert_weights_unchanged(freeze_record: dict[str, Any], weights: dict[str, float]) -> None:
    """Raise if live weights diverge from a previously frozen record."""
    frozen = freeze_record.get("weights") or {}
    live = {k: float(v) for k, v in sorted(weights.items())}
    if frozen != live:
        raise ValueError(
            "ENSEMBLE_WEIGHTS_MUTATED_AFTER_FREEZE: live weights differ from "
            f"frozen record (hash={freeze_record.get('content_hash')}). "
            "Calibration claim barred (SPEC §21.3)."
        )


__all__ = [
    "ALLOWED_SPLIT_MODES",
    "SplitMode",
    "require_chronological",
    "enumerate_fy_origins",
    "reconstruct_pit",
    "freeze_weights_before_test",
    "assert_weights_unchanged",
]
