"""Annual transition matrix with Dirichlet prior and support counts (REGIME-TRANSITION-DIRICHLET-v1).

Pairs are (posterior at p, posterior at p + 1 year). With quarterly features the pairs overlap
(Q1->Q1, Q2->Q2, ...), so each pair gets weight 1/k (k = observations per year). The effective
count is then roughly the number of years, not 4x it. Expected counts use the product of the two
posteriors (soft labels): N_ij = sum_pairs w P_t(i) P_t+1y(j). Posterior Dirichlet alpha' = alpha + N.
mean_ij = alpha'_ij / sum_j alpha'_ij. Rows with support (sum_j N_ij) below min_state_support are flagged
PRIOR_DOMINATED_ROW.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from vms.regimes.schemas import PeriodPosterior, TransitionModel
from vms.schemas.config import RegimeConfig


def _plus_year(d: date) -> date:
    return date(d.year + 1, d.month, 28 if (d.month == 2 and d.day == 29) else d.day)


def estimate_transitions(history: Sequence[PeriodPosterior], cfg: RegimeConfig,
                         cadence: str | None) -> TransitionModel:
    states = list(cfg.states)
    k = len(states)
    by_date = {h.period_end: h for h in history}
    per_year = 4 if cadence == "quarterly" else 1
    w = 1.0 / per_year
    n = [[0.0] * k for _ in range(k)]
    pairs = 0
    for h in history:
        nxt = by_date.get(_plus_year(h.period_end))
        if nxt is None:
            continue
        pairs += 1
        for i, si in enumerate(states):
            for j, sj in enumerate(states):
                n[i][j] += w * h.probabilities[si] * nxt.probabilities[sj]
    a0 = [[cfg.transition_prior.stay if i == j else cfg.transition_prior.move for j in range(k)] for i in range(k)]
    a1 = [[a0[i][j] + n[i][j] for j in range(k)] for i in range(k)]
    mean, sd = [], []
    for row in a1:
        s = sum(row)
        mean.append([x / s for x in row])
        sd.append([math.sqrt((x / s) * (1 - x / s) / (s + 1)) for x in row])
    support = [sum(r) for r in n]
    flags = []
    low = [states[i] for i, s in enumerate(support) if s < cfg.min_state_support]
    if low:
        flags.append("PRIOR_DOMINATED_ROW:" + ",".join(low))
    if sum(support) < k * cfg.min_state_support:
        flags.append("STATES_EXCEED_SUPPORT")   # more states than the data can support (SPEC §7.4)
    if pairs == 0:
        flags.append("NO_TRANSITIONS_OBSERVED_PRIOR_ONLY")
    return TransitionModel(states=states, prior_alpha=a0, expected_counts=n, posterior_alpha=a1, mean=mean,
                           posterior_sd=sd, row_support=support, n_pairs=pairs, pair_weight=w, flags=flags)


def propagate(p: dict[str, float], tm: TransitionModel) -> dict[str, float]:
    """One annual step: p' = p x mean transition matrix."""
    out = {s: 0.0 for s in tm.states}
    for i, si in enumerate(tm.states):
        for j, sj in enumerate(tm.states):
            out[sj] += p[si] * tm.mean[i][j]
    tot = sum(out.values())
    return {s: v / tot for s, v in out.items()}
