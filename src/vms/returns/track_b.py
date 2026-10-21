"""VMS-0.2 Phase 10: Track B exit-price conditioned return distributions (SPEC §15 / §20).

Uses future *market* exit prices from ExitPriceBundle — never silently treats Track A
intrinsic / horizon-equity as the terminal price.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Literal, Mapping, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.market_pricing.exit_prices import ExitPriceBundle, ExitPricePath
from vms.returns.formula import (
    annualized_geometric,
    cite_return_assumptions_phase10,
    holding_period_return,
    return_components,
)
from vms.returns.horizon_value import cumulative_dps
from vms.returns.stats import summarize_returns
from vms.schemas.config import LoadedConfig, ReturnsConfig
from vms.statements.paths import FinancialPathBundle, FinancialPathRecord

TRACK_B_RETURNS_VERSION = "RET-TRACK-B-1"
COMPOUNDING_CONVENTION = "DIVIDEND-NO-REINVEST-v1"
PRICE_SERIES_CONVENTION = "PATH-DILUTED-SHARES-ALIGNED-v1"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathReturnTrackB(_M):
    path_id: str
    entry_price: float
    horizon_years: int
    holding_return: float | None
    annualized_geometric: float | None
    terminal_price: float | None
    shareholder_distributions: float | None
    price_component: float | None = None
    distribution_component: float | None = None
    initial_market_state: str | None = None
    terminal_market_state: str | None = None
    fundamental_path_id: str | None = None
    valid: bool
    invalid_reason: str | None = None
    flags: list[str] = Field(default_factory=list)
    lineage: dict[str, Any] = Field(default_factory=dict)


class CellSummaryTrackB(_M):
    entry_price: float
    relative_to_spot: float
    horizon_years: int
    stats: dict[str, Any]
    n_valid: int
    n_failed: int


class StateConditional(_M):
    state_kind: Literal["market_pricing", "fundamental"]
    state: str
    n_paths: int
    cells: list[CellSummaryTrackB]
    flags: list[str] = Field(default_factory=list)


class ReturnDistributionBundleTrackB(_M):
    schema_kind: Literal["ReturnDistributionBundleTrackB"] = "ReturnDistributionBundleTrackB"
    version: str = TRACK_B_RETURNS_VERSION
    label: str = "TRACK_B_ENTRY_PRICE_CONDITIONED_RETURNS"
    spot_price: float
    entry_prices: list[float]
    relative_to_spot: list[float]
    horizons_years: list[int]
    n_input_exit_paths: int
    n_valid_cells_paths: int
    mixture: list[CellSummaryTrackB]
    by_market_state: list[StateConditional] = Field(default_factory=list)
    by_fundamental_state: list[StateConditional] = Field(default_factory=list)
    path_returns: list[PathReturnTrackB]
    exit_ref: dict[str, Any]
    compounding_convention: str = COMPOUNDING_CONVENTION
    price_series_convention: str = PRICE_SERIES_CONVENTION
    dividend_treatment: str = "DIVIDEND-NO-REINVEST-v1"
    buyback_treatment: str = "SHARE_COUNT_ONLY_NO_CASH_ADDON"
    issuance_treatment: str = "SHARE_COUNT_AND_CASH_IN_METRICS_ONLY"
    split_treatment: str = "REFLECTED_IN_SHARE_PATH"
    assumptions: list[str]
    flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
    content_fingerprint: str = ""
    investment_value: str = "INVESTMENT_VALUE_NOT_ESTABLISHED"


def entry_price_grid(spot_price: float, relative: Sequence[float]) -> list[float]:
    if not (math.isfinite(spot_price) and spot_price > 0):
        raise ValueError(f"spot_price must be finite and > 0; got {spot_price!r}")
    out = [float(spot_price * r) for r in relative]
    if any(not (math.isfinite(p) and p > 0) for p in out):
        raise ValueError(f"entry prices must be finite and > 0; got {out}")
    return out


def merge_entry_prices(
    spot_price: float,
    *,
    relative_to_spot: Sequence[float],
    user_prices: Sequence[float] | None = None,
) -> tuple[list[float], list[float]]:
    """Grid around spot plus optional absolute user prices. Relatives reported vs spot."""
    prices = entry_price_grid(spot_price, relative_to_spot)
    if user_prices:
        for p in user_prices:
            if not (math.isfinite(p) and p > 0):
                raise ValueError(f"user entry price must be finite and > 0; got {p!r}")
            if all(abs(p - q) > 1e-12 * max(1.0, abs(q)) for q in prices):
                prices.append(float(p))
        prices = sorted(prices)
    rel = [p / spot_price for p in prices]
    return prices, rel


def _fin_map(financial: FinancialPathBundle | None) -> dict[str, FinancialPathRecord]:
    if financial is None:
        return {}
    return {r.path_id: r for r in financial.paths}


def _shareholder_distributions(
    rec: FinancialPathRecord | None,
    horizon_years: int,
    *,
    explicit: float | None = None,
) -> tuple[float | None, list[str]]:
    """Cash DPS cumulative; buybacks/issuance/splits not double-counted as cash."""
    flags: list[str] = []
    if explicit is not None:
        if not math.isfinite(explicit):
            return None, ["NONFINITE_EXPLICIT_DISTRIBUTIONS"]
        return float(explicit), ["EXPLICIT_DISTRIBUTIONS_OVERRIDE"]
    if rec is None:
        return 0.0, ["NO_FINANCIAL_PATH_DISTRIBUTIONS_ZERO"]
    dps = cumulative_dps(rec, horizon_years)
    if dps is None:
        return None, ["DPS_UNDEFINED"]
    # Diagnostic: if repurchases present, confirm we do not add them as cash
    ys = [str(y) for y in (rec.projection.years[:horizon_years] if rec.projection else [])]
    if any((rec.share_repurchases.get(y, 0.0) or 0.0) != 0.0 for y in ys):
        flags.append("BUYBACKS_PRESENT_SHARE_COUNT_ONLY")
    if any((rec.share_issuance_proceeds.get(y, 0.0) or 0.0) != 0.0 for y in ys):
        flags.append("ISSUANCE_PRESENT_SHARE_COUNT_ONLY")
    return float(dps), flags


def pathwise_returns_improve_at_lower_price_track_b(
    path_returns: Sequence[PathReturnTrackB],
) -> bool:
    """SPEC §15.3 / §21.2: fixed future price+distributions ⇒ higher P0 cannot improve pathwise R."""
    by_key: dict[tuple[str, int], list[PathReturnTrackB]] = {}
    for pr in path_returns:
        if (
            not pr.valid
            or pr.holding_return is None
            or pr.terminal_price is None
            or pr.shareholder_distributions is None
        ):
            continue
        by_key.setdefault((pr.path_id, pr.horizon_years), []).append(pr)
    for rows in by_key.values():
        rows = sorted(rows, key=lambda r: r.entry_price)
        xs = [r.terminal_price + r.shareholder_distributions for r in rows]
        if any(abs(x - xs[0]) > 1e-6 * max(1.0, abs(xs[0])) for x in xs):
            return False
        for a, b in zip(rows, rows[1:]):
            if not (a.entry_price < b.entry_price - 1e-15):
                continue
            xa = a.terminal_price + a.shareholder_distributions
            if not ((xa - a.entry_price) > (xa - b.entry_price) - 1e-9):
                return False
            if xa > 0 and not (a.holding_return > b.holding_return - 1e-12):
                return False
    return True


def content_fingerprint_track_b(bundle: ReturnDistributionBundleTrackB) -> str:
    payload = {
        "spot": bundle.spot_price,
        "prices": bundle.entry_prices,
        "horizons": bundle.horizons_years,
        "exit": bundle.exit_ref,
        "means": [(c.entry_price, c.horizon_years, c.stats.get("mean")) for c in bundle.mixture],
        "n_valid": bundle.n_valid_cells_paths,
    }
    return hashlib.sha256(repr(payload).encode()).hexdigest()[:16]


def build_return_distributions_from_exit_prices(
    *,
    exit_prices: ExitPriceBundle,
    spot_price: float,
    loaded: LoadedConfig | None = None,
    financial: FinancialPathBundle | None = None,
    entry_prices: Sequence[float] | None = None,
    relative_to_spot: Sequence[float] | None = None,
    user_entry_prices: Sequence[float] | None = None,
    horizons_years: Sequence[int] | None = None,
    returns_config: ReturnsConfig | None = None,
    explicit_distributions: Mapping[tuple[str, int], float] | None = None,
    fundamental_state_by_path: Mapping[str, str] | None = None,
    path_return_cap: int = 50_000,
) -> ReturnDistributionBundleTrackB:
    """Build entry-price × horizon return distributions from Track B exit prices."""
    if loaded is not None:
        cfg_rel = list(loaded.config.entry_price_grid.relative_to_spot)
        rcfg = returns_config or loaded.config.returns
        default_horizons = list(loaded.config.horizons_years)
    else:
        cfg_rel = [0.8, 1.0, 1.2]
        rcfg = returns_config or ReturnsConfig(
            loss_thresholds=[-0.4, -0.2], hurdles=[0.0, 0.08, 0.15], cvar_levels=[0.95, 0.99]
        )
        default_horizons = list(exit_prices.horizons_years)

    rel_in = list(relative_to_spot) if relative_to_spot is not None else cfg_rel
    if entry_prices is not None:
        prices = [float(p) for p in entry_prices]
        if any(not (math.isfinite(p) and p > 0) for p in prices):
            raise ValueError(f"entry_prices must be finite and > 0; got {prices}")
        if user_entry_prices:
            for p in user_entry_prices:
                if all(abs(float(p) - q) > 1e-12 * max(1.0, abs(q)) for q in prices):
                    prices.append(float(p))
            prices = sorted(prices)
        rel_used = [p / spot_price for p in prices]
    else:
        prices, rel_used = merge_entry_prices(
            spot_price, relative_to_spot=rel_in, user_prices=user_entry_prices
        )

    avail_h = set(int(h) for h in exit_prices.horizons_years)
    req_h = list(horizons_years) if horizons_years is not None else default_horizons
    horizons = [int(h) for h in req_h if int(h) in avail_h]
    if not horizons:
        raise ValueError(
            f"no requested horizons {req_h} intersect exit-price horizons {sorted(avail_h)}"
        )

    fin = _fin_map(financial)
    # Index valid exit paths by (path_id, horizon)
    exit_index: dict[tuple[str, int], ExitPricePath] = {}
    for p in exit_prices.paths:
        if p.valid and p.exit_price_per_share is not None and math.isfinite(p.exit_price_per_share):
            exit_index[(p.path_id, int(p.horizon_years))] = p

    path_returns: list[PathReturnTrackB] = []
    cells_data: dict[tuple[int, int], list[tuple[float, float, float, float | None, str | None, str | None]]] = {
        (i, h): [] for i in range(len(prices)) for h in horizons
    }
    n_failed_cells: dict[tuple[int, int], int] = {(i, h): 0 for i in range(len(prices)) for h in horizons}

    # Unique path ids that have at least one valid exit at a requested horizon
    path_ids = sorted({pid for (pid, h) in exit_index if h in horizons})

    for pid in path_ids:
        rec = fin.get(pid)
        fund_state = None if fundamental_state_by_path is None else fundamental_state_by_path.get(pid)
        for h in horizons:
            ep = exit_index.get((pid, h))
            if ep is None:
                for i in range(len(prices)):
                    n_failed_cells[(i, h)] += 1
                continue
            dist, dflags = _shareholder_distributions(
                rec,
                h,
                explicit=None if explicit_distributions is None else explicit_distributions.get((pid, h)),
            )
            if dist is None:
                for i in range(len(prices)):
                    n_failed_cells[(i, h)] += 1
                    if len(path_returns) < path_return_cap:
                        path_returns.append(
                            PathReturnTrackB(
                                path_id=pid,
                                entry_price=prices[i],
                                horizon_years=h,
                                holding_return=None,
                                annualized_geometric=None,
                                terminal_price=ep.exit_price_per_share,
                                shareholder_distributions=None,
                                initial_market_state=ep.initial_market_state,
                                terminal_market_state=ep.terminal_market_state,
                                fundamental_path_id=pid,
                                valid=False,
                                invalid_reason="DISTRIBUTIONS_UNDEFINED",
                                flags=dflags,
                                lineage={"exit_lineage": ep.lineage},
                            )
                        )
                continue
            term = float(ep.exit_price_per_share)  # type: ignore[arg-type]
            for i, p0 in enumerate(prices):
                r, fl = holding_period_return(
                    value_per_share=term, cum_dps=dist, entry_price=p0
                )
                if r is None:
                    n_failed_cells[(i, h)] += 1
                    if len(path_returns) < path_return_cap:
                        path_returns.append(
                            PathReturnTrackB(
                                path_id=pid,
                                entry_price=p0,
                                horizon_years=h,
                                holding_return=None,
                                annualized_geometric=None,
                                terminal_price=term,
                                shareholder_distributions=dist,
                                initial_market_state=ep.initial_market_state,
                                terminal_market_state=ep.terminal_market_state,
                                fundamental_path_id=pid,
                                valid=False,
                                invalid_reason="RETURN_UNDEFINED",
                                flags=fl + dflags,
                                lineage={"exit_lineage": ep.lineage},
                            )
                        )
                    continue
                ag, agf = annualized_geometric(holding_return=r, horizon_years=h)
                comps = return_components(terminal_price=term, shareholder_distributions=dist, entry_price=p0)
                cells_data[(i, h)].append(
                    (r, term, dist, ag, ep.terminal_market_state, fund_state)
                )
                if len(path_returns) < path_return_cap:
                    path_returns.append(
                        PathReturnTrackB(
                            path_id=pid,
                            entry_price=p0,
                            horizon_years=h,
                            holding_return=r,
                            annualized_geometric=ag,
                            terminal_price=term,
                            shareholder_distributions=dist,
                            price_component=comps["price_component"],
                            distribution_component=comps["distribution_component"],
                            initial_market_state=ep.initial_market_state,
                            terminal_market_state=ep.terminal_market_state,
                            fundamental_path_id=pid,
                            valid=True,
                            flags=fl + agf + dflags,
                            lineage={
                                "exit_lineage": ep.lineage,
                                "metric_id": ep.metric_id,
                                "terminal_multiple": ep.terminal_multiple,
                                "scenario_kind": ep.scenario_kind,
                                "intrinsic_value_used": ep.intrinsic_value_used,
                            },
                        )
                    )

    def _cell(
        i: int,
        h: int,
        rows: list[tuple[float, float, float, float | None, str | None, str | None]],
    ) -> CellSummaryTrackB:
        if not rows:
            return CellSummaryTrackB(
                entry_price=prices[i],
                relative_to_spot=rel_used[i],
                horizon_years=h,
                stats={"n": 0},
                n_valid=0,
                n_failed=n_failed_cells[(i, h)],
            )
        rs = np.array([r for r, _, _, _, _, _ in rows], dtype=float)
        terms = np.array([t for _, t, _, _, _, _ in rows], dtype=float)
        dists = np.array([d for _, _, d, _, _, _ in rows], dtype=float)
        ags = np.array([a if a is not None else math.nan for _, _, _, a, _, _ in rows], dtype=float)
        stats = summarize_returns(
            rs,
            vps=terms,
            loss_thresholds=list(rcfg.loss_thresholds),
            hurdles=list(rcfg.hurdles),
            cvar_levels=list(rcfg.cvar_levels),
            ann_geo=ags,
            shareholder_distributions=dists,
            entry_price=prices[i],
        )
        return CellSummaryTrackB(
            entry_price=prices[i],
            relative_to_spot=rel_used[i],
            horizon_years=h,
            stats=stats,
            n_valid=len(rows),
            n_failed=n_failed_cells[(i, h)],
        )

    mixture = [_cell(i, h, cells_data[(i, h)]) for h in horizons for i in range(len(prices))]

    def _by_state(
        kind: Literal["market_pricing", "fundamental"],
        state_idx: int,
    ) -> list[StateConditional]:
        # state_idx: 4 = market terminal state, 5 = fundamental
        states_present: set[str] = set()
        for rows in cells_data.values():
            for row in rows:
                s = row[state_idx]
                if s:
                    states_present.add(s)
        out: list[StateConditional] = []
        for state in sorted(states_present):
            cells_s: list[CellSummaryTrackB] = []
            n_paths_state = 0
            for h in horizons:
                for i in range(len(prices)):
                    rows = [row for row in cells_data[(i, h)] if row[state_idx] == state]
                    cells_s.append(_cell(i, h, rows))
            # count unique paths with this state at first horizon
            h0 = horizons[0]
            n_paths_state = len(
                {
                    pid
                    for pid in path_ids
                    if (pid, h0) in exit_index
                    and (
                        (exit_index[(pid, h0)].terminal_market_state == state)
                        if kind == "market_pricing"
                        else (fundamental_state_by_path or {}).get(pid) == state
                    )
                }
            )
            out.append(
                StateConditional(
                    state_kind=kind,
                    state=state,
                    n_paths=n_paths_state,
                    cells=cells_s,
                )
            )
        return out

    by_mkt = _by_state("market_pricing", 4)
    by_fund = _by_state("fundamental", 5) if fundamental_state_by_path else []

    flags: list[str] = []
    quality: list[str] = ["TRACK_B_EXIT_PRICES", "INVESTMENT_VALUE_NOT_ESTABLISHED"]
    if any(c.n_valid == 0 for c in mixture):
        flags.append("SOME_CELLS_EMPTY")
    if exit_prices.scenario_kind != "TERMINAL_MULTIPLE_DEFAULT":
        flags.append(f"EXIT_SCENARIO_{exit_prices.scenario_kind}")
    if any(p.intrinsic_value_used for p in exit_prices.paths if p.valid):
        flags.append("SOME_PATHS_USED_EXPLICIT_CONVERGENCE")
    # Monotonicity diagnostic on means
    for h in horizons:
        means = []
        ordered = True
        for i in range(len(prices)):
            st = next(
                c for c in mixture if c.horizon_years == h and abs(c.entry_price - prices[i]) < 1e-12
            )
            means.append(st.stats.get("mean"))
        if all(m is not None for m in means) and len(means) >= 2:
            for j in range(len(means) - 1):
                if means[j] + 1e-9 < means[j + 1]:
                    ordered = False
                    break
            if not ordered:
                flags.append("MIXTURE_MEAN_NONMONOTONE_IN_PRICE")

    # Internal consistency quality check across cells
    for c in mixture:
        s = c.stats
        if s.get("n", 0) == 0:
            continue
        if "QUANTILE_ORDER_INCONSISTENT" in s.get("flags", []):
            quality.append("QUANTILE_ORDER_INCONSISTENT")
        if "ES_INCONSISTENT_WITH_QUANTILE" in s.get("flags", []):
            quality.append("ES_INCONSISTENT_WITH_QUANTILE")

    notes = [
        "Track B: TerminalPrice = market exit price (ExitPriceBundle), not intrinsic value.",
        "Compounding: DIVIDEND-NO-REINVEST-v1 (cumulative cash DPS; no dividend reinvestment).",
        "Buybacks/issuance/splits: share-count / metric effects only — no cash double-count.",
        "Annualized geometric: ANNUALIZED-GEO-ENDYEAR-v1 = (1+R)^(1/H)-1.",
        "No Kelly / portfolio sizing. INVESTMENT_VALUE_NOT_ESTABLISHED.",
        "Lower entry price does not alter fundamental or market-pricing odds; paths held fixed across the price grid.",
    ]
    exit_ref = {
        "scenario_kind": exit_prices.scenario_kind,
        "transition_model_id": exit_prices.transition_model_id,
        "metric_id": exit_prices.metric_id,
        "n_input_paths": exit_prices.n_input_paths,
        "n_valid": exit_prices.n_valid,
        "n_failed": exit_prices.n_failed,
        "default_forbids_intrinsic_copy": exit_prices.default_forbids_intrinsic_copy,
        "dependence_on_fundamentals": exit_prices.dependence_on_fundamentals,
        "version": exit_prices.version,
    }
    assumptions = cite_return_assumptions_phase10()
    bundle = ReturnDistributionBundleTrackB(
        spot_price=spot_price,
        entry_prices=prices,
        relative_to_spot=rel_used,
        horizons_years=horizons,
        n_input_exit_paths=exit_prices.n_input_paths,
        n_valid_cells_paths=len(path_ids),
        mixture=mixture,
        by_market_state=by_mkt,
        by_fundamental_state=by_fund,
        path_returns=path_returns,
        exit_ref=exit_ref,
        assumptions=assumptions,
        flags=sorted(set(flags)),
        notes=notes,
        quality_flags=sorted(set(quality)),
    )
    fp = content_fingerprint_track_b(bundle)
    return bundle.model_copy(update={"content_fingerprint": fp})
