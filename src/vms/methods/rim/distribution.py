"""R2b: P2 ROE path distribution + ke sensitivity grid for deposit-taking FI RIM.

Primary NI policy: NI_t = ROE_path × beginning common equity_t (RIM-NI-P2-ROE-v1).
ROE paths: bootstrap with replacement from PIT history (fixed seed).
P1 constant last-FY common NI retained as control (single path).
No ensemble across methods or ke values.
R10/R11: primary ke cell retains capped finite-positive path VPS samples
(``vps_samples`` / ``n_vps_samples``) for PRIOR_ONLY live ingest.
Cap policy: deterministic stride subsample (not path-order prefix).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from vms.assumptions import cite
from vms.drivers.history import extract_annual
from vms.methods.rim.from_snapshot import (
    NI_POLICY_P1,
    NI_POLICY_P2,
    common_equity_components,
    common_ni_from_eps,
    fy_dps_from_sharebonus,
)
from vms.methods.rim.math import residual_income_value
from vms.pit.snapshot import PITSnapshot
from vms.schemas.config import LoadedConfig

DEFAULT_KE_GRID = (0.08, 0.09, 0.10)


@dataclass(frozen=True)
class RoeHistory:
    years: list[int]  # ROE year t (NI year)
    roe: list[float]
    flags: list[str] = field(default_factory=list)


# Cap persisted path VPS samples in rim_distribution artifacts (R10/R11).
LIVE_SAMPLE_CAP = 96


def stride_cap_indices(n: int, cap: int = LIVE_SAMPLE_CAP) -> list[int]:
    """Deterministic systematic indices for capping a length-``n`` series to ``cap``.

    Contract (ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-STRIDE-CAP-v1):
    - ``n <= cap`` → ``list(range(n))``
    - ``n > cap`` → primary ``[(i * n) // cap for i in range(cap)]``;
      if collisions shrink the set (defensive; not expected when ``n >= cap``),
      fill with the smallest unused indices in ascending walk until ``cap``.
    - Return sorted ascending indices (preserves relative path order).
    """
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


def subsample_cap(
    xs: Sequence[float],
    cap: int = LIVE_SAMPLE_CAP,
) -> list[float]:
    """Finite-positive series → at most ``cap`` values via deterministic stride.

    Full-set percentiles must still be computed from the uncapped series by the caller.
    Subsample ≠ calibration coverage.
    """
    n = len(xs)
    if n <= cap:
        return [float(x) for x in xs]
    return [float(xs[k]) for k in stride_cap_indices(n, cap)]


@dataclass(frozen=True)
class KeGridCell:
    cost_of_equity: float
    n_valid: int
    n_invalid: int
    equity_p05: float | None
    equity_p50: float | None
    equity_p95: float | None
    vps_p05: float | None
    vps_p50: float | None
    vps_p95: float | None
    vps_mean: float | None
    # R10: capped finite positive path VPS (primary ke cell only when retained).
    vps_samples: tuple[float, ...] | None = None
    n_vps_samples: int = 0


@dataclass(frozen=True)
class RimDistributionResult:
    ok: bool
    ineligible_reason: str | None
    flags: list[str]
    assumption_ids: list[str]
    roe_history: RoeHistory | None
    seed: int
    n_paths: int
    years: int
    book_equity_0: float | None
    dps: float | None
    diluted_shares: float | None
    ke_grid: list[KeGridCell]
    p1_control: dict[str, Any]
    detail: str = ""


def historical_common_roe(
    snap: PITSnapshot,
    *,
    zeros_explicit: bool = True,
    max_years: int = 10,
) -> RoeHistory:
    """Build PIT-truncated ROE_t = common_NI_t / common_equity_{t-1} (up to max_years)."""
    h = extract_annual(snap)
    flags: list[str] = []
    pairs: list[tuple[int, float]] = []
    for i, y in enumerate(h.years):
        if i == 0:
            continue
        y_prev = h.years[i - 1]
        be_prev, _, cflags, err = common_equity_components(
            h, year=y_prev, zeros_explicit=zeros_explicit,
        )
        flags.extend(cflags)
        if err or be_prev is None or be_prev <= 0:
            flags.append(f"ROE_SKIP_NO_BE_PREV@{y}")
            continue
        ni, _, ni_err = common_ni_from_eps(h, snap, year=y)
        if ni is None:
            # fallback: parent_net_income only if labeled (not for primary hist if EPS missing)
            flags.append(f"ROE_SKIP_NO_COMMON_NI@{y}:{ni_err}")
            continue
        pairs.append((y, float(ni) / float(be_prev)))
    # keep most recent max_years
    pairs = pairs[-max_years:]
    if not pairs:
        flags.append("ROE_HISTORY_EMPTY")
    return RoeHistory(
        years=[p[0] for p in pairs],
        roe=[p[1] for p in pairs],
        flags=sorted(set(flags)),
    )


def _percentile(xs: Sequence[float], q: float) -> float | None:
    if not xs:
        return None
    return float(np.percentile(np.asarray(xs, dtype=float), q))


def _build_ni_div_path(
    *,
    book_equity_0: float,
    roe: float,
    years: int,
    dps: float,
    shares: float,
    oci_constant: float | None,
) -> tuple[list[float], list[float], list[float] | None]:
    """P2 path: NI_t = roe * BE_{t-1}; Div_t = dps * shares; roll BE via CS."""
    ni: list[float] = []
    div: list[float] = []
    oci: list[float] | None = None if oci_constant is None else []
    be = float(book_equity_0)
    div_amt = float(dps) * float(shares)
    for _ in range(years):
        ni_t = float(roe) * be
        ni.append(ni_t)
        div.append(div_amt)
        oci_t = 0.0 if oci_constant is None else float(oci_constant)
        if oci is not None:
            oci.append(oci_t)
        be = be + ni_t - div_amt + oci_t  # net_issuance=0
    return ni, div, oci


def run_rim_distribution(
    snap: PITSnapshot,
    *,
    loaded: LoadedConfig,
    book_equity_0: float,
    book_equity_year: int,
    dps: float,
    diluted_shares: float,
    years: int | None = None,
    n_paths: int = 200,
    seed: int = 42,
    ke_grid: Sequence[float] | None = None,
    zeros_explicit: bool = True,
    max_roe_history: int = 10,
    oci_constant: float | None = None,
    p1_common_ni: float | None = None,
    goodwill: float | None = None,
) -> RimDistributionResult:
    """Bootstrap P2 ROE paths × ke grid. Returns distribution summaries (no ensemble)."""
    if years is None:
        years = int(loaded.config.projection.default_years)
    kes = list(ke_grid) if ke_grid is not None else list(DEFAULT_KE_GRID)
    g = float(loaded.config.terminal_value.terminal_growth)
    max_g = float(loaded.config.terminal_value.max_terminal_growth)
    min_margin = float(loaded.config.terminal_value.min_wacc_minus_g)
    forecast_years = [book_equity_year + i for i in range(1, years + 1)]

    flags: list[str] = ["NI_POLICY_P2_ROE_BOOTSTRAP", "NO_ENSEMBLE"]
    aids = cite(
        "RIM-CLEAN-SURPLUS-v1",
        "RIM-COST-OF-EQUITY-v1",
        "NO-DOUBLE-EV-BRIDGE-v1",
        "RIM-COMMON-EQUITY-v1",
        "RIM-NI-P2-ROE-v1",
        "RIM-DPS-SHAREBONUS-v1",
        "RIM-KE-GRID-v1",
        "RIM-CS-ZEROS-EXPLICIT-v1",
    )

    hist = historical_common_roe(snap, zeros_explicit=zeros_explicit, max_years=max_roe_history)
    flags.extend(hist.flags)
    if len(hist.roe) < 2:
        return RimDistributionResult(
            ok=False,
            ineligible_reason="INSUFFICIENT_ROE_HISTORY",
            flags=sorted(set(flags)),
            assumption_ids=aids,
            roe_history=hist,
            seed=seed,
            n_paths=n_paths,
            years=years,
            book_equity_0=book_equity_0,
            dps=dps,
            diluted_shares=diluted_shares,
            ke_grid=[],
            p1_control={},
            detail=f"need >=2 ROE observations; got {len(hist.roe)}",
        )

    rng = np.random.default_rng(int(seed))
    # sample ROE levels (constant ROE per path across forecast years)
    draws = rng.choice(np.asarray(hist.roe, dtype=float), size=int(n_paths), replace=True)

    cells: list[KeGridCell] = []
    for ke_i, ke in enumerate(kes):
        vps_ok: list[float] = []
        eq_ok: list[float] = []
        n_invalid = 0
        for roe in draws:
            ni, div, oci = _build_ni_div_path(
                book_equity_0=book_equity_0,
                roe=float(roe),
                years=years,
                dps=dps,
                shares=diluted_shares,
                oci_constant=oci_constant,
            )
            res = residual_income_value(
                book_equity_0=book_equity_0,
                net_income=ni,
                cost_of_equity=float(ke),
                dividends=div,
                net_issuance=None,
                oci=oci,
                years=forecast_years,
                terminal_growth=g,
                max_terminal_growth=max_g,
                min_ke_minus_g=min_margin,
                diluted_shares=diluted_shares,
                zeros_explicit=True,
                goodwill=goodwill,
                goodwill_haircut=0.0,
            )
            if not res.valid or res.value_per_share is None or res.equity_value is None:
                n_invalid += 1
                continue
            vps_ok.append(float(res.value_per_share))
            eq_ok.append(float(res.equity_value))
        # R10/R11: retain stride-capped finite-positive path VPS on primary ke only.
        retain_src = [
            v for v in vps_ok
            if v == v and abs(v) != float("inf") and v > 0
        ]
        retain = ke_i == 0 and len(retain_src) >= 1
        capped = tuple(subsample_cap(retain_src, LIVE_SAMPLE_CAP)) if retain else None
        cells.append(
            KeGridCell(
                cost_of_equity=float(ke),
                n_valid=len(vps_ok),
                n_invalid=n_invalid,
                equity_p05=_percentile(eq_ok, 5),
                equity_p50=_percentile(eq_ok, 50),
                equity_p95=_percentile(eq_ok, 95),
                vps_p05=_percentile(vps_ok, 5),
                vps_p50=_percentile(vps_ok, 50),
                vps_p95=_percentile(vps_ok, 95),
                vps_mean=(float(np.mean(vps_ok)) if vps_ok else None),
                vps_samples=capped,
                n_vps_samples=(len(capped) if capped is not None else 0),
            )
        )

    # P1 control at first ke (config / grid[0])
    p1_control: dict[str, Any] = {"ni_policy": NI_POLICY_P1}
    if p1_common_ni is not None:
        ke0 = float(kes[0])
        div_amt = float(dps) * float(diluted_shares)
        res = residual_income_value(
            book_equity_0=book_equity_0,
            net_income=[float(p1_common_ni)] * years,
            cost_of_equity=ke0,
            dividends=[div_amt] * years,
            years=forecast_years,
            terminal_growth=g,
            max_terminal_growth=max_g,
            min_ke_minus_g=min_margin,
            diluted_shares=diluted_shares,
            zeros_explicit=True,
            goodwill=goodwill,
        )
        p1_control.update({
            "cost_of_equity": ke0,
            "common_ni": float(p1_common_ni),
            "valid": res.valid,
            "equity_value": res.equity_value,
            "value_per_share": res.value_per_share,
            "flags": list(res.flags),
        })

    # AC: p05 < p50 < p95 on primary ke cell when enough paths
    primary = cells[0] if cells else None
    if primary and primary.n_valid >= 3:
        if not (
            primary.vps_p05 is not None
            and primary.vps_p50 is not None
            and primary.vps_p95 is not None
            and primary.vps_p05 < primary.vps_p50 < primary.vps_p95
        ):
            flags.append("VPS_PERCENTILES_NOT_STRICTLY_ORDERED")

    ok = bool(cells) and any(c.n_valid > 0 for c in cells)
    if cells and cells[0].vps_samples:
        aids = sorted(
            set(aids) | set(cite("ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-STRIDE-CAP-v1"))
        )
    return RimDistributionResult(
        ok=ok,
        ineligible_reason=None if ok else "NO_VALID_DISTRIBUTION_PATHS",
        flags=sorted(set(flags)),
        assumption_ids=aids,
        roe_history=hist,
        seed=int(seed),
        n_paths=int(n_paths),
        years=int(years),
        book_equity_0=float(book_equity_0),
        dps=float(dps),
        diluted_shares=float(diluted_shares),
        ke_grid=cells,
        p1_control=p1_control,
        detail=(
            f"P2 bootstrap n_paths={n_paths} seed={seed} roe_hist_n={len(hist.roe)} "
            f"ke_grid={kes}; ni_policy={NI_POLICY_P2}"
        ),
    )


def dps_or_ineligible(snap: PITSnapshot, fiscal_year: int) -> tuple[float | None, list[str]]:
    return fy_dps_from_sharebonus(snap, fiscal_year=fiscal_year)
