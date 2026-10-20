"""Entry-price-conditioned return distributions (SPEC §12, Phase 7)."""

from __future__ import annotations

import hashlib
import math
from typing import Any, Literal, Mapping, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.regimes import RegimeResult
from vms.returns.formula import annualized_geometric, cite_return_assumptions, holding_period_return
from vms.returns.horizon_value import equity_at_horizon
from vms.returns.stats import summarize_returns
from vms.sampling.schemas import SimulationBundle
from vms.schemas.config import LoadedConfig
from vms.statements.paths import FinancialPathBundle, FinancialPathRecord
from vms.valuation.value import PathValuation, ValuationBundle

RETURNS_VERSION = "RET-1"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathReturn(_M):
    path_id: str
    entry_price: float
    horizon_years: int
    holding_return: float | None
    annualized_geometric: float | None
    value_per_share: float | None
    cum_dps: float | None
    initial_state: str | None = None
    valid: bool
    invalid_reason: str | None = None
    flags: list[str] = Field(default_factory=list)


class CellSummary(_M):
    entry_price: float
    relative_to_spot: float
    horizon_years: int
    stats: dict[str, Any]
    n_valid: int
    n_failed: int


class RegimeConditional(_M):
    state: str
    n_paths: int
    support_count: float | None
    parameter_uncertainty_flags: list[str]
    cells: list[CellSummary]


class ReturnDistributionBundle(_M):
    schema_kind: Literal["ReturnDistributionBundle"] = "ReturnDistributionBundle"
    version: str = RETURNS_VERSION
    label: str = "ENTRY_PRICE_CONDITIONED_RETURNS"
    spot_price: float
    entry_prices: list[float]
    relative_to_spot: list[float]
    horizons_years: list[int]
    n_input_paths: int
    n_valid_paths: int
    mixture: list[CellSummary]
    by_regime: list[RegimeConditional]
    path_returns: list[PathReturn]  # may be capped for JSON; parquet holds full
    valuation_ref: dict[str, Any]
    dividend_treatment: str = "DIVIDEND-NO-REINVEST-v1"
    assumptions: list[str]
    flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def entry_price_grid(spot_price: float, relative: Sequence[float]) -> list[float]:
    if not (math.isfinite(spot_price) and spot_price > 0):
        raise ValueError(f"spot_price must be finite and > 0; got {spot_price!r}")
    out = [float(spot_price * r) for r in relative]
    if any(not (math.isfinite(p) and p > 0) for p in out):
        raise ValueError(f"entry prices must be finite and > 0; got {out}")
    return out


def _fin_by_id(financial: FinancialPathBundle) -> dict[str, FinancialPathRecord]:
    return {r.path_id: r for r in financial.paths}


def _val_by_id(valuation: ValuationBundle) -> dict[str, PathValuation]:
    return {p.path_id: p for p in valuation.paths if p.path_id != "central" or True}


def _initial_states(bundle: SimulationBundle | None) -> dict[str, str]:
    if bundle is None:
        return {}
    out: dict[str, str] = {}
    for p in [bundle.central, *bundle.paths]:
        if p.valid and p.years:
            out[p.path_id] = p.years[0].state
    return out


def _horizon_indices(available_years: list[int], requested: Sequence[int]) -> list[int]:
    """Map requested H (year count) to 1-based indices capped by available forecast length."""
    n = len(available_years)
    return [h for h in requested if 1 <= h <= n]


def build_return_distributions(
    *,
    valuation: ValuationBundle,
    financial: FinancialPathBundle,
    loaded: LoadedConfig,
    spot_price: float,
    entry_prices: Sequence[float] | None = None,
    horizons_years: Sequence[int] | None = None,
    simulation: SimulationBundle | None = None,
    regimes: RegimeResult | None = None,
    path_return_cap: int = 50_000,
) -> ReturnDistributionBundle:
    cfg = loaded.config
    rel = list(cfg.entry_price_grid.relative_to_spot)
    prices = list(entry_prices) if entry_prices is not None else entry_price_grid(spot_price, rel)
    # recover relatives for reporting
    rel_used = [p / spot_price for p in prices]
    horizons = list(horizons_years) if horizons_years is not None else list(cfg.horizons_years)
    horizons = _horizon_indices(list(financial.years), horizons)
    if not horizons:
        raise ValueError("no requested horizons fall within the forecast year range")

    fin_map = _fin_by_id(financial)
    val_map = _val_by_id(valuation)
    states = _initial_states(simulation)
    rcfg = cfg.returns

    # Only VALID DCF paths that also have VALID financial records
    valid_ids = [pid for pid in valuation.valid_path_ids if pid in fin_map and fin_map[pid].status == "VALID"]
    path_returns: list[PathReturn] = []
    # Collect arrays per (price_idx, horizon) for mixture
    cells_data: dict[tuple[int, int], list[tuple[float, float, float | None, str | None]]] = {
        (i, h): [] for i in range(len(prices)) for h in horizons
    }
    n_failed_cells: dict[tuple[int, int], int] = {(i, h): 0 for i in range(len(prices)) for h in horizons}

    # Precompute horizon equity per path (independent of entry price)
    horizon_cache: dict[tuple[str, int], Any] = {}
    for pid in valid_ids:
        pv = val_map.get(pid)
        rec = fin_map[pid]
        if pv is None or pv.status != "VALID" or pv.wacc_inputs is None:
            continue
        for h in horizons:
            he = equity_at_horizon(rec=rec, wacc_inputs=pv.wacc_inputs, loaded=loaded, horizon_index=h)
            horizon_cache[(pid, h)] = he

    for pid in valid_ids:
        st = states.get(pid)
        for h in horizons:
            he = horizon_cache.get((pid, h))
            if he is None or not he.valid or he.value_per_share is None or he.cum_dps is None:
                for i in range(len(prices)):
                    n_failed_cells[(i, h)] += 1
                    if len(path_returns) < path_return_cap:
                        path_returns.append(PathReturn(
                            path_id=pid, entry_price=prices[0] if prices else float("nan"),
                            horizon_years=h, holding_return=None, annualized_geometric=None,
                            value_per_share=None if he is None else he.value_per_share,
                            cum_dps=None if he is None else he.cum_dps, initial_state=st,
                            valid=False, invalid_reason=None if he is None else he.invalid_reason,
                            flags=[] if he is None else he.flags))
                continue
            for i, p0 in enumerate(prices):
                r, fl = holding_period_return(value_per_share=he.value_per_share, cum_dps=he.cum_dps,
                                             entry_price=p0)
                if r is None:
                    n_failed_cells[(i, h)] += 1
                    if len(path_returns) < path_return_cap:
                        path_returns.append(PathReturn(
                            path_id=pid, entry_price=p0, horizon_years=h, holding_return=None,
                            annualized_geometric=None, value_per_share=he.value_per_share,
                            cum_dps=he.cum_dps, initial_state=st, valid=False,
                            invalid_reason="RETURN_UNDEFINED", flags=fl))
                    continue
                ag, agf = annualized_geometric(holding_return=r, horizon_years=h)
                cells_data[(i, h)].append((r, he.value_per_share, ag, st))
                if len(path_returns) < path_return_cap:
                    path_returns.append(PathReturn(
                        path_id=pid, entry_price=p0, horizon_years=h, holding_return=r,
                        annualized_geometric=ag, value_per_share=he.value_per_share,
                        cum_dps=he.cum_dps, initial_state=st, valid=True, flags=fl + agf))

    def _cell(i: int, h: int, rows: list[tuple[float, float, float | None, str | None]]) -> CellSummary:
        if not rows:
            return CellSummary(entry_price=prices[i], relative_to_spot=rel_used[i], horizon_years=h,
                               stats={"n": 0}, n_valid=0, n_failed=n_failed_cells[(i, h)])
        rs = np.array([r for r, _, _, _ in rows], dtype=float)
        vs = np.array([v for _, v, _, _ in rows], dtype=float)
        ags = np.array([a if a is not None else math.nan for _, _, a, _ in rows], dtype=float)
        stats = summarize_returns(rs, vps=vs, loss_thresholds=list(rcfg.loss_thresholds),
                                  hurdles=list(rcfg.hurdles), cvar_levels=list(rcfg.cvar_levels),
                                  ann_geo=ags)
        return CellSummary(entry_price=prices[i], relative_to_spot=rel_used[i], horizon_years=h,
                           stats=stats, n_valid=len(rows), n_failed=n_failed_cells[(i, h)])

    mixture = [_cell(i, h, cells_data[(i, h)]) for h in horizons for i in range(len(prices))]

    # Regime-conditional diagnostics
    by_regime: list[RegimeConditional] = []
    support_map: dict[str, float] = {}
    pu_flags: list[str] = []
    if regimes is not None:
        states_list = list(regimes.current.states)
        for i, s in enumerate(states_list):
            if i < len(regimes.transitions.row_support):
                support_map[s] = float(regimes.transitions.row_support[i])
        pu_flags = list(regimes.transitions.flags) + list(regimes.current.flags)
        for state in states_list:
            support = support_map.get(state)
            rare = support is not None and support < cfg.regimes.min_state_support
            state_flags = list(pu_flags)
            if rare:
                state_flags = sorted(set(state_flags) | {"RARE_STATE_LOW_SUPPORT"})
            cells_s: list[CellSummary] = []
            n_paths_state = 0
            for h in horizons:
                for i in range(len(prices)):
                    rows = [row for row in cells_data[(i, h)] if row[3] == state]
                    if h == horizons[0] and i == 0:
                        n_paths_state = len({pid for pid in valid_ids if states.get(pid) == state})
                    cells_s.append(_cell(i, h, rows))
            # recount properly
            n_paths_state = len({pid for pid in valid_ids if states.get(pid) == state})
            by_regime.append(RegimeConditional(
                state=state, n_paths=n_paths_state, support_count=support,
                parameter_uncertainty_flags=state_flags, cells=cells_s))

    flags: list[str] = []
    if any(c.n_valid == 0 for c in mixture):
        flags.append("SOME_CELLS_EMPTY")
    if any("RARE_STATE_LOW_SUPPORT" in r.parameter_uncertainty_flags for r in by_regime):
        flags.append("RARE_STATE_RESULTS_PRESENT")
    # Monotonicity check on means (diagnostic, not a hard fail): lower price => higher mean return
    for h in horizons:
        means = []
        for i in range(len(prices)):
            st = next(c for c in mixture if c.horizon_years == h and abs(c.entry_price - prices[i]) < 1e-12)
            means.append(st.stats.get("mean"))
        if all(m is not None for m in means) and len(means) >= 2:
            if any(means[j] + 1e-9 < means[j + 1] for j in range(len(means) - 1)):
                # prices sorted ascending via rel sorted => means should be nonincreasing in price
                # wait: lower price => higher return, so as price increases mean should decrease
                flags.append("MIXTURE_MEAN_NONMONOTONE_IN_PRICE")

    notes = [
        "Dividend treatment: DIVIDEND-NO-REINVEST-v1 (cumulative cash DPS, no reinvestment).",
        "Horizon equity: HORIZON-EQUITY-REMAINING-PV-v1 (remaining FCFF PV + TV to H, then bridge).",
        "Annualized geometric: ANNUALIZED-GEO-ENDYEAR-v1.",
        "No claim of universally optimal buy price; allocation is a portfolio decision.",
        "Lower entry price does not alter fundamental regime odds; paths are held fixed across the price grid.",
    ]
    vref = {
        "n_valid_dcf": valuation.n_valid_dcf,
        "valid_path_id_hash": valuation.aggregates.get("valid_path_id_hash"),
        "terminal_growth": valuation.terminal_growth,
        "wacc_point": valuation.wacc_point.wacc,
    }
    return ReturnDistributionBundle(
        spot_price=spot_price, entry_prices=prices, relative_to_spot=rel_used,
        horizons_years=horizons, n_input_paths=valuation.n_input, n_valid_paths=len(valid_ids),
        mixture=mixture, by_regime=by_regime, path_returns=path_returns, valuation_ref=vref,
        assumptions=cite_return_assumptions() + cite("EV-EQUITY-BRIDGE-v1", "TV-GORDON-v1"),
        flags=sorted(set(flags)), notes=notes)


def pathwise_returns_improve_at_lower_price(path_returns: Sequence[PathReturn]) -> bool:
    """SPEC §12.4 / §19: holding path+horizon fixed, lower P0 improves pathwise outcome.

    Terminal per-share wealth X = VPS + cum_DPS is invariant across the price grid.
    Dollar excess X - P0 strictly rises as P0 falls.
    Percentage return R=(X-P0)/P0 strictly rises as P0 falls whenever X > 0
    (when X <= 0, percentage returns are not monotone in P0; dollar excess still is).
    """
    by_key: dict[tuple[str, int], list[PathReturn]] = {}
    for pr in path_returns:
        if not pr.valid or pr.holding_return is None or pr.value_per_share is None or pr.cum_dps is None:
            continue
        by_key.setdefault((pr.path_id, pr.horizon_years), []).append(pr)
    for rows in by_key.values():
        rows = sorted(rows, key=lambda r: r.entry_price)
        xs = [r.value_per_share + r.cum_dps for r in rows]
        if any(abs(x - xs[0]) > 1e-6 * max(1.0, abs(xs[0])) for x in xs):
            return False  # future wealth must be fixed across entry prices
        for a, b in zip(rows, rows[1:]):
            if not (a.entry_price < b.entry_price - 1e-15):
                continue
            xa = a.value_per_share + a.cum_dps
            # dollar excess improves at lower price
            if not ((xa - a.entry_price) > (xa - b.entry_price) - 1e-9):
                return False
            if xa > 0 and not (a.holding_return > b.holding_return - 1e-12):
                return False
    return True


def content_fingerprint(bundle: ReturnDistributionBundle) -> str:
    payload = {
        "spot": bundle.spot_price,
        "prices": bundle.entry_prices,
        "horizons": bundle.horizons_years,
        "val": bundle.valuation_ref,
        "means": [(c.entry_price, c.horizon_years, c.stats.get("mean")) for c in bundle.mixture],
    }
    return hashlib.sha256(repr(payload).encode()).hexdigest()[:16]
