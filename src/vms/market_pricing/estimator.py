"""Independent market-pricing state estimator (SPEC §14.3 / Phase 9).

Does NOT take fundamental regimes as inputs for inference unless an explicitly
configured dependence overlay is applied after estimation.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from vms.assumptions import cite
from vms.market_pricing.config import MarketPricingConfig, default_market_pricing_config
from vms.market_pricing.schemas import (
    MARKET_PRICING_STATES,
    MarketPricingStatePosterior,
    fallback_market_pricing_prior,
    unavailable_market_pricing,
)


def _classify_z(z: float) -> str:
    """Map z-score of current multiple vs history to a market-pricing state."""
    if z <= -1.5:
        return "COMPRESSED"
    if z >= 2.5:
        return "DISLOCATION"
    if z >= 1.0:
        return "EXPANDED"
    return "NORMAL"


def estimate_market_pricing_state(
    *,
    current_multiple: float | None = None,
    historical_multiples: Sequence[float] | None = None,
    config: MarketPricingConfig | None = None,
    use_fallback_when_unavailable: bool = True,
) -> MarketPricingStatePosterior:
    """Estimate COMPRESSED/NORMAL/EXPANDED/DISLOCATION from market multiples only.

    Independent of fundamental regimes (MARKET-PRICING-INDEPENDENT-v1).
    Short / missing history → UNAVAILABLE + optional explicit fallback prior.
    """
    cfg = config or default_market_pricing_config()
    hist = [float(x) for x in (historical_multiples or []) if x is not None and np.isfinite(x) and x > 0]
    assumptions = cite(
        "MARKET-PRICING-SCHEMA-v1",
        "MARKET-PRICING-INDEPENDENT-v1",
        "MARKET-PRICING-ESTIMATOR-PHASE9-v1",
        "MARKET-PRICING-FALLBACK-PRIOR-v1",
    )

    if (
        current_multiple is None
        or not np.isfinite(current_multiple)
        or current_multiple <= 0
        or len(hist) < cfg.min_history_obs_for_estimation
    ):
        reason = (
            f"insufficient market-multiple history for estimation "
            f"(n={len(hist)} < min={cfg.min_history_obs_for_estimation}); "
            "not inferred from fundamentals"
        )
        if use_fallback_when_unavailable:
            post = fallback_market_pricing_prior(
                cfg.fallback_prior.as_dict(),
                reason=reason,
            )
            return post.model_copy(
                update={
                    "assumptions": sorted(set(post.assumptions) | set(assumptions)),
                    "diagnostics": {
                        **post.diagnostics,
                        "n_history": len(hist),
                        "min_required": cfg.min_history_obs_for_estimation,
                        "current_multiple": current_multiple,
                    },
                }
            )
        return unavailable_market_pricing(reason=reason)

    arr = np.asarray(hist, dtype=float)
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    scale = 1.4826 * mad if mad > 1e-12 else float(np.std(arr)) or 1.0
    z = (float(current_multiple) - med) / scale
    state = _classify_z(z)
    # Soft probabilities around the point classification (explicit, not calibrated).
    base = {s: 0.05 for s in MARKET_PRICING_STATES}
    base[state] = 0.70
    rem = 1.0 - sum(base.values())
    # Give remaining mass to neighbors
    neighbors = {
        "COMPRESSED": ("NORMAL",),
        "NORMAL": ("COMPRESSED", "EXPANDED"),
        "EXPANDED": ("NORMAL", "DISLOCATION"),
        "DISLOCATION": ("EXPANDED",),
    }[state]
    for n in neighbors:
        base[n] += rem / len(neighbors)
    # renormalize
    ssum = sum(base.values())
    probs = {k: v / ssum for k, v in base.items()}
    return MarketPricingStatePosterior(
        status="AVAILABLE",
        states=list(MARKET_PRICING_STATES),
        probabilities=probs,
        source="multiple_zscore_classifier_v1",
        reason=None,
        estimator_phase="PHASE_9",
        confidence="MEDIUM" if len(hist) >= cfg.min_history_obs_for_estimation * 2 else "LOW",
        flags=["MARKET_PRICING_ZSCORE_CLASSIFIER", "NOT_CALIBRATED"],
        assumptions=assumptions,
        dependence_on_fundamentals="NONE",
        diagnostics={
            "n_history": len(hist),
            "median": med,
            "mad_scale": scale,
            "z_score": z,
            "point_state": state,
            "current_multiple": float(current_multiple),
        },
    )


def apply_configured_dependence(
    posterior: MarketPricingStatePosterior,
    *,
    fundamental_state: str | None,
    tilt: Mapping[str, Mapping[str, float]] | None,
) -> MarketPricingStatePosterior:
    """Apply an explicitly configured fundamental→market tilt. Default path never calls this."""
    if posterior.status != "AVAILABLE" or not tilt or fundamental_state is None:
        return posterior
    factors = tilt.get(fundamental_state)
    if not factors or posterior.probabilities is None:
        return posterior
    raw = {
        s: max(posterior.probabilities[s] * float(factors.get(s, 1.0)), 0.0)
        for s in posterior.states
    }
    ssum = sum(raw.values())
    if ssum <= 0:
        return posterior
    probs = {k: v / ssum for k, v in raw.items()}
    return posterior.model_copy(
        update={
            "probabilities": probs,
            "dependence_on_fundamentals": "CONFIGURED",
            "source": (posterior.source or "") + "+configured_fundamental_tilt",
            "flags": sorted(set(posterior.flags) | {"CONFIGURED_FUNDAMENTAL_DEPENDENCE"}),
            "diagnostics": {
                **posterior.diagnostics,
                "fundamental_state_tilt": fundamental_state,
            },
        }
    )


def sample_state(
    posterior: MarketPricingStatePosterior,
    *,
    rng: np.random.Generator,
    fallback_prior: Mapping[str, float] | None = None,
) -> tuple[str, list[str]]:
    """Draw one market-pricing state; use fallback prior if posterior UNAVAILABLE."""
    flags: list[str] = []
    if posterior.status == "AVAILABLE" and posterior.probabilities:
        states = list(posterior.states)
        p = np.array([posterior.probabilities[s] for s in states], dtype=float)
        p = p / p.sum()
        return str(rng.choice(states, p=p)), flags
    prior = dict(fallback_prior or {s: 1.0 / len(MARKET_PRICING_STATES) for s in MARKET_PRICING_STATES})
    states = [s for s in MARKET_PRICING_STATES if s in prior]
    p = np.array([prior[s] for s in states], dtype=float)
    p = p / p.sum()
    flags.append("SAMPLED_FROM_FALLBACK_PRIOR")
    return str(rng.choice(states, p=p)), flags
