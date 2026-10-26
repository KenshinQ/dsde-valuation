"""R11: deterministic stride subsample for live sample cap (AC1–AC4, AC7)."""

from __future__ import annotations

from pathlib import Path


from vms.assumptions import ASSUMPTIONS, cite
from vms.methods.rim.distribution import (
    LIVE_SAMPLE_CAP,
    stride_cap_indices,
    subsample_cap,
)


def _expected_indices(n: int, cap: int) -> list[int]:
    """Mirror the locked fill rule for AC2 assertions."""
    if n <= 0 or cap <= 0:
        return []
    if n <= cap:
        return list(range(n))
    primary = [(i * n) // cap for i in range(cap)]
    seen: set[int] = set()
    idx: list[int] = []
    for k in primary:
        if k not in seen:
            seen.add(k)
            idx.append(k)
    j = 0
    while len(idx) < cap and j < n:
        if j not in seen:
            seen.add(j)
            idx.append(j)
        j += 1
    return sorted(idx)[:cap]


def test_ac1_n_le_cap_retains_all_in_order():
    xs = [1.0, 2.0, 3.0, 4.0]
    assert subsample_cap(xs, cap=96) == xs
    assert subsample_cap(xs, cap=4) == xs
    assert subsample_cap([], cap=96) == []
    assert stride_cap_indices(4, 96) == [0, 1, 2, 3]
    assert stride_cap_indices(96, 96) == list(range(96))


def test_ac2_stride_index_formula_and_fill():
    cap = LIVE_SAMPLE_CAP
    assert cap == 96
    for n in (cap + 1, cap + 20, 100, 200, 1000):
        idx = stride_cap_indices(n, cap)
        assert len(idx) == cap
        assert idx == sorted(idx)
        assert idx == _expected_indices(n, cap)
        # Relative order / uniqueness
        assert len(set(idx)) == cap
        assert idx[0] >= 0 and idx[-1] < n
        xs = [float(i) for i in range(n)]
        got = subsample_cap(xs, cap)
        assert got == [xs[k] for k in idx]
        # When stride indices differ from 0..cap-1, samples leave the path-order prefix.
        # (For n just above cap, e.g. cap+1, the formula can still equal the prefix.)
        if idx != list(range(cap)):
            assert got != xs[:cap]


def test_ac2_cap_plus_one_boundary():
    cap = 96
    n = cap + 1
    idx = stride_cap_indices(n, cap)
    assert len(idx) == cap
    assert idx == _expected_indices(n, cap)
    # Primary formula alone is unique when n >= cap; no fill needed.
    primary = sorted({(i * n) // cap for i in range(cap)})
    assert len(primary) == cap
    assert idx == primary


def test_ac4_deterministic_pure():
    xs = [float(i) * 0.1 + 1.0 for i in range(LIVE_SAMPLE_CAP + 40)]
    a = subsample_cap(xs)
    b = subsample_cap(xs)
    assert a == b
    assert len(a) == LIVE_SAMPLE_CAP


def test_ac7_assumption_registered_and_citable():
    aid = "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-STRIDE-CAP-v1"
    assert aid in ASSUMPTIONS
    assert "stride" in ASSUMPTIONS[aid].lower() or "STRIDE" in aid
    assert "calibration coverage" in ASSUMPTIONS[aid].lower() or "≠" in ASSUMPTIONS[aid]
    assert cite(aid) == [aid]
    # Parent still active (adapter may cite LIVE-SAMPLES).
    assert "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1" in ASSUMPTIONS
    assert "STRIDE-CAP" in ASSUMPTIONS["ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1"]


def test_ac1_ac2_ac3_ac4_distribution_integration(repo: Path):
    """Track A: stride cap, percentiles from full set, deterministic."""
    from tests.unit.methods.test_rim_r2_distribution import _multi_year_snap

    from vms.methods.rim.distribution import run_rim_distribution
    from vms.methods.rim.from_snapshot import rim_inputs_from_snapshot
    from vms.schemas.config import load_config

    loaded = load_config(repo / "config/default.yaml")
    snap = _multi_year_snap()
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=True)
    assert bridge.ok
    n_paths = LIVE_SAMPLE_CAP + 20
    kwargs = dict(
        snap=snap,
        loaded=loaded,
        book_equity_0=float(bridge.common_equity_0),
        book_equity_year=int(bridge.book_equity_year),
        dps=float(bridge.last_fy_dps),
        diluted_shares=float(bridge.rim_inputs["diluted_shares"]),
        years=5,
        n_paths=n_paths,
        seed=7,
        ke_grid=(0.09,),
        p1_common_ni=float(bridge.last_fy_ni),
        goodwill=bridge.goodwill_0,
        oci_constant=-0.2e9,
    )
    d1 = run_rim_distribution(**kwargs)
    d2 = run_rim_distribution(**kwargs)
    assert d1.ok and d2.ok
    p1, p2 = d1.ke_grid[0], d2.ke_grid[0]
    assert p1.n_valid > LIVE_SAMPLE_CAP
    assert p1.n_vps_samples == LIVE_SAMPLE_CAP
    assert p1.vps_samples is not None
    assert list(p1.vps_samples) == list(p2.vps_samples)  # AC4
    # AC3: percentiles present and identical across runs (full-set)
    assert p1.vps_p05 == p2.vps_p05
    assert p1.vps_p50 == p2.vps_p50
    assert p1.vps_p95 == p2.vps_p95
    assert p1.vps_p05 is not None and p1.vps_p50 is not None and p1.vps_p95 is not None
    assert p1.vps_p05 < p1.vps_p50 < p1.vps_p95
    # Not path-order prefix of a dense 1..n identity (values are VPS; check cite)
    assert (
        "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-STRIDE-CAP-v1" in d1.assumption_ids
    )
    # Samples equal applying subsample_cap to a reconstructed bank is hard without
    # exposing uncapped; assert length + determinism + stride ≠ first-N identity
    # by checking indices on a synthetic parallel bank of same length.
    synth = [float(i) for i in range(p1.n_valid)]
    capped_synth = subsample_cap(synth, LIVE_SAMPLE_CAP)
    idx = stride_cap_indices(p1.n_valid, LIVE_SAMPLE_CAP)
    assert capped_synth == [synth[k] for k in idx]
    assert len(capped_synth) == LIVE_SAMPLE_CAP
    if idx != list(range(LIVE_SAMPLE_CAP)):
        assert capped_synth != synth[:LIVE_SAMPLE_CAP]


def test_ac1_ac2_track_b_collect_then_stride(tmp_path: Path, repo: Path):
    """Track B must collect all finite-positive then stride (no early-break)."""
    from tests.unit.methods.test_rim_r2cd_track_b import _build_years

    from vms.methods.rim.from_snapshot import rim_inputs_from_snapshot
    from vms.methods.rim.track_b_exit import run_rim_track_b
    from vms.schemas.config import load_config

    loaded = load_config(repo / "config/default.yaml")
    snap = _build_years(14)
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, equity_basis="common")
    assert bridge.ok
    n_paths = LIVE_SAMPLE_CAP + 10
    tb1 = run_rim_track_b(
        snap,
        bridge=bridge,
        loaded=loaded,
        years=3,
        n_paths=n_paths,
        seed=11,
        horizons_years=(1, 3),
    )
    tb2 = run_rim_track_b(
        snap,
        bridge=bridge,
        loaded=loaded,
        years=3,
        n_paths=n_paths,
        seed=11,
        horizons_years=(1, 3),
    )
    assert tb1.ok and tb1.exit_prices is not None
    cell1 = tb1.exit_prices["summaries"]["1"]
    cell2 = tb2.exit_prices["summaries"]["1"]
    assert "exit_vps_samples" in cell1
    assert cell1["n_exit_vps_samples"] == len(cell1["exit_vps_samples"])
    assert cell1["n_exit_vps_samples"] <= LIVE_SAMPLE_CAP
    assert cell1["exit_vps_samples"] == cell2["exit_vps_samples"]
    assert "p50" in cell1  # full-set summary untouched
    assert (
        "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-STRIDE-CAP-v1" in tb1.assumption_ids
    )


def test_docs_mention_stride_closed():
    proto = Path("docs/calibration_protocol.md").read_text()
    assert "STRIDE-CAP-v1" in proto or "STRIDE-CAP" in proto
    assert "Prefix-cap:" in proto and "CLOSED" in proto
    r10 = Path("PHASE_R10_LIVE_SAMPLES_DONE.md").read_text()
    assert "CLOSED" in r10 and "R11" in r10
    r11 = Path("PHASE_R11_PREFIX_CAP_SUBSAMPLE_DONE.md").read_text()
    assert "SF4 CLOSED-by-replacement" in r11
    assert "ENSEMBLE_CALIBRATED" in r11
