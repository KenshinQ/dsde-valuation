"""R2d: map RIM P2 common-equity book paths → FinancialPathRecord for exit-price engine.

Puts rolled common equity into the ``total_equity@year`` projection slot so the
existing ``pb`` metric denominator works, with flag COMMON_EQUITY_IN_PB_DENOM_FIELD.
Dividends are cash amounts (DPS × shares) for cumulative_dps.
Never copies intrinsic VPS into exit prices.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

from vms.assumptions import cite
from vms.drivers.profiles import ProfileResolution, ProfileStatus
from vms.methods.rim.distribution import historical_common_roe
from vms.pit.snapshot import PITSnapshot
from vms.statements.ledger import TracedValue
from vms.statements.paths import FinancialPathBundle, FinancialPathRecord
from vms.statements.projection import PATH_LABEL, ProjectionResult


def _stub_resolution() -> ProfileResolution:
    return ProfileResolution(
        status=ProfileStatus.SUPPORTED,
        profile_id="rim_book_path",
        scheme=None,
        industry=None,
        reason="R2d RIM common-equity book path for deposit-taking-FI P/B exit (not industrial projection)",
        flags=["RIM_BOOK_PATH_NOT_OPERATING_PROJECTION"],
        assumptions=cite("RIM-EXIT-OWN-PB-HIST-v1", "RIM-COMMON-EQUITY-v1", "RIM-NI-P2-ROE-v1"),
    )


def _roll_common_equity_path(
    *,
    book_equity_0: float,
    roe: float,
    years: Sequence[int],
    dps: float,
    shares: float,
    oci_constant: float | None,
) -> tuple[dict[int, float], dict[int, float], dict[int, float]]:
    """Return (be_by_year, ni_by_year, div_by_year) for forecast years."""
    be = float(book_equity_0)
    div_amt = float(dps) * float(shares)
    be_y: dict[int, float] = {}
    ni_y: dict[int, float] = {}
    div_y: dict[int, float] = {}
    for y in years:
        ni_t = float(roe) * be
        oci_t = 0.0 if oci_constant is None else float(oci_constant)
        be = be + ni_t - div_amt + oci_t
        be_y[int(y)] = be
        ni_y[int(y)] = ni_t
        div_y[int(y)] = div_amt
    return be_y, ni_y, div_y


def _projection_for_path(
    *,
    instrument_id: str,
    as_of_iso: str,
    years: list[int],
    be_y: dict[int, float],
    ni_y: dict[int, float],
    shares: float,
) -> ProjectionResult:
    items: dict[str, TracedValue] = {}
    for y in years:
        items[f"total_equity@{y}"] = TracedValue(
            value=float(be_y[y]),
            formula="common_equity_roll_CS",
            inputs=["book_equity_prev", "ni", "div", "oci"],
        )
        items[f"parent_net_income@{y}"] = TracedValue(
            value=float(ni_y[y]),
            formula="roe*beginning_common_equity",
            inputs=["roe", "book_equity_prev"],
        )
        items[f"diluted_shares@{y}"] = TracedValue(
            value=float(shares),
            formula="constant_shares",
            inputs=["diluted_shares_0"],
        )
    return ProjectionResult(
        label=PATH_LABEL,
        status="VALID",
        instrument_id=instrument_id,
        as_of=as_of_iso,
        profile=_stub_resolution(),
        policy={"policy_id": "rim_constant_dps"},
        base_year=years[0] - 1 if years else None,
        years=list(years),
        items=items,
        fcff=None,
        fcfe=None,
        violations=[],
        missing_inputs=[],
        flags=[
            "RIM_P2_BOOK_PATH",
            "COMMON_EQUITY_IN_PB_DENOM_FIELD",
            "NO_OPERATING_FCFF_PROJECTION",
        ],
        assumptions=cite(
            "RIM-NI-P2-ROE-v1",
            "RIM-COMMON-EQUITY-v1",
            "RIM-EXIT-OWN-PB-HIST-v1",
            "MARKET-PRICING-NO-SILENT-INTRINSIC-EXIT-v1",
        ),
    )


def build_rim_book_path_bundle(
    snap: PITSnapshot,
    *,
    book_equity_0: float,
    book_equity_year: int,
    dps: float,
    diluted_shares: float,
    years: int,
    n_paths: int,
    seed: int,
    zeros_explicit: bool = True,
    oci_constant: float | None = None,
    max_roe_history: int = 10,
) -> FinancialPathBundle | None:
    """Bootstrap P2 ROE → FinancialPathBundle usable by generate_exit_prices(metric=pb)."""
    if years < 1 or n_paths < 1:
        return None
    if not (math.isfinite(book_equity_0) and book_equity_0 > 0):
        return None
    if not (math.isfinite(diluted_shares) and diluted_shares > 0):
        return None
    hist = historical_common_roe(snap, zeros_explicit=zeros_explicit, max_years=max_roe_history)
    if len(hist.roe) < 2:
        return None

    forecast_years = [int(book_equity_year) + i for i in range(1, years + 1)]
    rng = np.random.default_rng(int(seed))
    draws = rng.choice(np.asarray(hist.roe, dtype=float), size=int(n_paths), replace=True)

    records: list[FinancialPathRecord] = []
    for i, roe in enumerate(draws):
        be_y, ni_y, div_y = _roll_common_equity_path(
            book_equity_0=float(book_equity_0),
            roe=float(roe),
            years=forecast_years,
            dps=float(dps),
            shares=float(diluted_shares),
            oci_constant=oci_constant,
        )
        proj = _projection_for_path(
            instrument_id=snap.instrument_id,
            as_of_iso=snap.as_of.isoformat(),
            years=forecast_years,
            be_y=be_y,
            ni_y=ni_y,
            shares=float(diluted_shares),
        )
        shares_map = {str(y): float(diluted_shares) for y in forecast_years}
        div_map = {str(y): float(div_y[y]) for y in forecast_years}
        beps_map = {
            str(y): float(be_y[y]) / float(diluted_shares) for y in forecast_years
        }
        records.append(
            FinancialPathRecord(
                path_id=f"rim_p2_{i}",
                kind="monte_carlo",
                status="VALID",
                excluded_from_aggregates=False,
                projection=proj,
                shares=shares_map,
                dividends=div_map,
                book_equity_per_share=beps_map,
                flags=[
                    "RIM_P2_BOOK_PATH",
                    "COMMON_EQUITY_IN_PB_DENOM_FIELD",
                    f"ROE={float(roe):.6g}",
                ],
            )
        )

    # central = path 0 (first draw) for bundle schema
    central = records[0]
    return FinancialPathBundle(
        label=PATH_LABEL,
        policy={"policy_id": "rim_constant_dps", "ni_policy": "P2"},
        base_year=int(book_equity_year),
        years=list(forecast_years),
        n_input_paths=len(records),
        n_valid=len(records),
        n_failed=0,
        central=central,
        paths=records,
        valid_path_ids=[r.path_id for r in records],
        failed=[],
        aggregates={"n": len(records), "note": "RIM P2 book paths; common equity in total_equity field"},
        sampler_ref={"seed": int(seed), "n_paths": int(n_paths), "roe_hist_n": len(hist.roe)},
        assumptions=cite(
            "RIM-NI-P2-ROE-v1",
            "RIM-COMMON-EQUITY-v1",
            "RIM-EXIT-OWN-PB-HIST-v1",
            "MARKET-PRICING-NO-SILENT-INTRINSIC-EXIT-v1",
        ),
        flags=["RIM_P2_BOOK_PATH_BUNDLE", "COMMON_EQUITY_IN_PB_DENOM_FIELD"],
    )
