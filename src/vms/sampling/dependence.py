"""Regime-conditional / pooled residual correlations with shrinkage (DRIVER-DEPENDENCE-v1)."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from vms.assumptions import cite
from vms.drivers.distributions import DistributionModel
from vms.sampling.schemas import MATERIAL_BLOCKS, DependenceModel

DEPENDENCE_VERSION = "DEP-1"


def _block_membership(names: Sequence[str]) -> dict[str, list[str]]:
    return {b: [d for d in names if d in members] for b, members in MATERIAL_BLOCKS.items() if any(d in members for d in names)}


def _align_residuals(dist: DistributionModel, names: Sequence[str]) -> tuple[np.ndarray, list[int]]:
    """Return (T x D) residual matrix for years where every driver has an observation; residual = (z-loc_hat)/s_hat."""
    by_year: dict[int, dict[str, float]] = {}
    for name in names:
        dd = dist.drivers[name]
        loc = dd.loc_hat if dd.loc_hat is not None else dd.prior_loc_z
        scale = dd.scale_hat if dd.scale_hat not in (None, 0.0) else dd.prior_scale_z
        for o in dd.observations:
            by_year.setdefault(o.year, {})[name] = (o.z - loc) / scale if scale else 0.0
    years = sorted(y for y, m in by_year.items() if all(n in m for n in names))
    if not years:
        return np.zeros((0, len(names))), []
    return np.array([[by_year[y][n] for n in names] for y in years], dtype=float), years


def _pearson(X: np.ndarray) -> np.ndarray:
    d = X.shape[1]
    if X.shape[0] < 2:
        return np.eye(d)
    # columns with ~0 variance are treated as uncorrelated (stay at identity row/col)
    std = X.std(axis=0)
    active = std > 1e-12
    C = np.eye(d)
    if active.sum() >= 2:
        idx = np.where(active)[0]
        sub = np.corrcoef(X[:, idx], rowvar=False)
        sub = np.nan_to_num(sub, nan=0.0)
        C[np.ix_(idx, idx)] = sub
    np.fill_diagonal(C, 1.0)
    w, V = np.linalg.eigh(C)
    w = np.clip(w, 1e-8, None)
    C = (V * w) @ V.T
    dinv = 1.0 / np.sqrt(np.clip(np.diag(C), 1e-12, None))
    C = C * dinv[:, None] * dinv[None, :]
    np.fill_diagonal(C, 1.0)
    return C


def shrink_correlation(raw: np.ndarray, n: int, k: float) -> tuple[np.ndarray, float]:
    """R = (n/(n+k)) R_hat + (k/(n+k)) I."""
    w = n / (n + k) if n + k > 0 else 0.0
    return w * raw + (1 - w) * np.eye(raw.shape[0]), w


def estimate_dependence(dist: DistributionModel, *, prior_strength: float, min_years: int,
                        states: Sequence[str] | None = None) -> DependenceModel:
    names = list(dist.drivers)
    X, years = _align_residuals(dist, names)
    n = len(years)
    flags: list[str] = []
    raw = _pearson(X) if n else np.eye(len(names))
    shrunk, w = shrink_correlation(raw, n, prior_strength)
    if n < min_years:
        flags.append("CORRELATION_SPARSE_HEAVY_SHRINK")
    if n < 2:
        flags.append("CORRELATION_IDENTITY_FALLBACK")
    # Never silently independent: even identity is explicit. Material blocks recorded.
    blocks = _block_membership(names)
    # within-block mean |corr| diagnostic
    for b, members in blocks.items():
        idx = [names.index(m) for m in members]
        if len(idx) < 2 or n < 2:
            continue
        sub = np.abs(shrunk[np.ix_(idx, idx)])
        off = sub[np.triu_indices(len(idx), 1)]
        if off.size and float(off.mean()) < 0.02 and n >= min_years:
            flags.append(f"BLOCK_NEAR_INDEPENDENT:{b}")  # data-driven near-independence, still jointly sampled
    return DependenceModel(
        method="gaussian_copula_shrunk_pearson", version=DEPENDENCE_VERSION, drivers=names,
        n_overlap_years=n, prior_strength=prior_strength, shrink_weight_data=w,
        correlation=shrunk.tolist(), correlation_raw=(raw.tolist() if n else None),
        regime_overrides={}, blocks={k: list(v) for k, v in blocks.items()},
        flags=sorted(set(flags)), assumptions=cite("DRIVER-DEPENDENCE-v1"))


def cholesky_psd(corr: np.ndarray) -> np.ndarray:
    try:
        return np.linalg.cholesky(corr)
    except np.linalg.LinAlgError:
        w, V = np.linalg.eigh(corr)
        w = np.clip(w, 1e-10, None)
        return np.linalg.cholesky((V * w) @ V.T)


def gaussian_copula_shocks(rng: np.random.Generator, chol: np.ndarray, df: float) -> np.ndarray:
    """Correlated Student-t shocks via Gaussian copula (normal → uniform → t.ppf)."""
    from scipy import stats
    z = chol @ rng.standard_normal(chol.shape[0])
    u = np.clip(stats.norm.cdf(z), 1e-12, 1 - 1e-12)
    return stats.t.ppf(u, df)
