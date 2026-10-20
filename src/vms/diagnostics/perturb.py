"""Perturbations that alter only the intended input (OAT isolation)."""

from __future__ import annotations

import copy
from typing import Any

from vms.regimes import RegimeResult
from vms.sampling.schemas import PathRecord, SimulationBundle, YearDrivers
from vms.schemas.config import LoadedConfig, VMSConfig


def shock_driver_bundle(bundle: SimulationBundle, driver: str, delta: float) -> tuple[SimulationBundle, dict[str, Any]]:
    """Add ``delta`` to one driver on every year of every path; leave all other drivers untouched."""
    def shock_path(p: PathRecord) -> PathRecord:
        years = []
        for yd in p.years:
            d = dict(yd.drivers)
            if driver in d:
                d[driver] = float(d[driver]) + delta
            years.append(yd.model_copy(update={"drivers": d, "flags": sorted(set(yd.flags) | {f"OAT_SHOCK:{driver}"})}))
        return p.model_copy(update={"years": years, "flags": sorted(set(p.flags) | {f"OAT_SHOCK:{driver}"})})

    new_paths = [shock_path(p) for p in bundle.paths]
    new_central = shock_path(bundle.central)
    meta = {
        "intended_input": driver,
        "shock": delta,
        "method": "pathwise_additive_driver_shock",
        "other_drivers_unmodified": True,
    }
    return bundle.model_copy(update={"paths": new_paths, "central": new_central,
                                     "flags": sorted(set(bundle.flags) | {f"OAT_SHOCK:{driver}"})}), meta


def driver_means(bundle: SimulationBundle) -> dict[str, float]:
    """Year-1 mean of each driver across valid MC paths (for OAT isolation checks)."""
    from collections import defaultdict
    import numpy as np
    acc: dict[str, list[float]] = defaultdict(list)
    for p in bundle.paths:
        if not p.valid or not p.years:
            continue
        for k, v in p.years[0].drivers.items():
            acc[k].append(float(v))
    return {k: float(np.mean(xs)) for k, xs in acc.items() if xs}


def ablation_driver_to_central(bundle: SimulationBundle, driver: str,
                               central_value: float) -> SimulationBundle:
    """Pathwise ablation: replace ``driver`` on all path-years with the central/path-independent value."""
    def abl(p: PathRecord) -> PathRecord:
        years = []
        for yd in p.years:
            d = dict(yd.drivers)
            if driver in d:
                d[driver] = float(central_value)
            years.append(yd.model_copy(update={"drivers": d, "flags": sorted(set(yd.flags) | {f"ABLATION:{driver}"})}))
        return p.model_copy(update={"years": years})
    return bundle.model_copy(update={
        "paths": [abl(p) for p in bundle.paths],
        "central": abl(bundle.central),
        "flags": sorted(set(bundle.flags) | {f"ABLATION:{driver}"}),
    })


def with_valuation_shocks(loaded: LoadedConfig, *, cost_of_equity_delta: float | None = None,
                          terminal_growth_delta: float | None = None,
                          exit_multiple_delta: float | None = None) -> LoadedConfig:
    cfg: VMSConfig = loaded.config
    v = cfg.valuation
    tv = cfg.terminal_value
    updates: dict[str, Any] = {}
    if cost_of_equity_delta is not None:
        ke = (v.cost_of_equity if v.cost_of_equity is not None
              else v.risk_free_rate + (v.beta if v.beta is not None else v.beta_prior) * v.erp)
        updates["cost_of_equity"] = ke + cost_of_equity_delta
    v2 = v.model_copy(update=updates) if updates else v
    if exit_multiple_delta is not None:
        em = v2.exit_multiple
        base_m = em.multiple if em.multiple is not None else em.shrink_prior
        v2 = v2.model_copy(update={"exit_multiple": em.model_copy(update={"multiple": base_m + exit_multiple_delta, "peers": []})})
    tv2 = tv
    if terminal_growth_delta is not None:
        g = tv.terminal_growth + terminal_growth_delta
        # keep within max; if would exceed, still apply but caller may see rejects
        tv2 = tv.model_copy(update={"terminal_growth": g, "max_terminal_growth": max(tv.max_terminal_growth, g)})
    cfg2 = cfg.model_copy(update={"valuation": v2, "terminal_value": tv2})
    return loaded.model_copy(update={"config": cfg2})


def tilt_posterior(regimes: RegimeResult, state: str, tilt: float) -> RegimeResult:
    """Shift probability mass toward ``state`` by ``tilt`` (renormalize). Other regime fields unchanged."""
    cur = regimes.current
    if state not in cur.states:
        raise ValueError(f"tilt state {state!r} not in {cur.states}")
    probs = dict(cur.probabilities)
    others = [s for s in cur.states if s != state]
    take = min(tilt, sum(probs[s] for s in others))
    if others and take > 0:
        total_o = sum(probs[s] for s in others)
        for s in others:
            probs[s] = max(probs[s] - take * (probs[s] / total_o if total_o > 0 else 0.0), 0.0)
        probs[state] = probs.get(state, 0.0) + take
    ssum = sum(probs.values())
    probs = {k: v / ssum for k, v in probs.items()}
    new_cur = cur.model_copy(update={"probabilities": probs,
                                     "flags": sorted(set(cur.flags) | {"POSTERIOR_TILT_OAT"})})
    return regimes.model_copy(update={"current": new_cur})


def boost_transition_stay(regimes: RegimeResult, boost: float) -> RegimeResult:
    """Add ``boost`` to each state's diagonal Dirichlet pseudo-count (stay probability)."""
    tm = regimes.transitions
    alpha = [list(row) for row in tm.posterior_alpha]
    for i in range(len(alpha)):
        alpha[i][i] = float(alpha[i][i]) + boost
    # recompute mean rows
    mean = []
    for row in alpha:
        s = sum(row) or 1.0
        mean.append([x / s for x in row])
    new_tm = tm.model_copy(update={"posterior_alpha": alpha, "mean": mean,
                                   "flags": sorted(set(tm.flags) | {"TRANSITION_STAY_BOOST_OAT"})})
    return regimes.model_copy(update={"transitions": new_tm})
