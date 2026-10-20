"""Interpretable rule-based fundamental regime classifier (REGIME-RULES-v1).

Soft rules (logistic memberships, sigma(x) = 1 / (1 + e^-x)) on PIT fundamental features:
    G_hi   = sigma((g - growth_high) / tau_growth)            strong growth
    G_neg  = sigma((growth_low - g) / tau_growth)             contraction
    M_down = sigma((-dm - margin_band) / tau_margin)          margin compression
    DET    = 1 - (1 - G_neg)(1 - M_down)                      soft OR
    weak   = min(1, P_prev(DETERIORATING) + recovery_carry x P_prev(RECOVERY))
    REC    = weak (1 - DET)
    GROWTH = (1 - weak)(1 - DET) G_hi
    STABLE = (1 - weak)(1 - DET)(1 - G_hi)
The four scores sum to 1 by construction (they partition the unit mass), so no ad-hoc renormalisation
hides errors. If one feature is missing, DET uses only the available component and G_hi = 0.5 (flagged
PARTIAL_FEATURES). Periods with neither feature are not classified (features.py drops them). With no previous period,
weak = 0 (flag NO_PREVIOUS_STATE). States dropped in config are merged into STABLE.
The recursion uses only the current and earlier periods: a filter, never a smoother.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime

from vms.assumptions import cite
from vms.pit.snapshot import local_date
from vms.regimes.hmm import RegimeModel
from vms.regimes.schemas import FeatureRow, FundamentalRegimePosterior, PeriodPosterior
from vms.schemas.config import FUNDAMENTAL_STATES, RegimeConfig

MODEL_ID = "FUND-RULES"


def _sig(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _entropy(p: dict[str, float]) -> float:
    return -sum(v * math.log(v) for v in p.values() if v > 0)


class RuleBasedClassifier(RegimeModel):
    model_id = MODEL_ID

    def __init__(self, cfg: RegimeConfig) -> None:
        self.cfg = cfg
        self.states = list(cfg.states)
        self.model_version = cfg.model_version

    def _merge(self, raw: dict[str, float]) -> dict[str, float]:
        out = {s: 0.0 for s in self.states}
        for s, v in raw.items():
            out[s if s in out else "STABLE"] += v
        return out

    def classify_period(self, row: FeatureRow, prev: dict[str, float] | None) -> PeriodPosterior:
        r = self.cfg.rules
        g, dm = row.revenue_growth_yoy, row.ebit_margin_change_yoy
        flags = []
        if g is None and dm is None:
            raise ValueError(f"{row.period_end}: no features; such periods must not be classified")
        g_hi = _sig((g - r.growth_high) / r.tau_growth) if g is not None else 0.5
        g_neg = _sig((r.growth_low - g) / r.tau_growth) if g is not None else None
        m_down = _sig((-dm - r.margin_band) / r.tau_margin) if dm is not None else None
        if g is None or dm is None:
            flags.append("PARTIAL_FEATURES")
        det = 1.0 - (1.0 - (g_neg or 0.0)) * (1.0 - (m_down or 0.0))
        if prev is None:
            weak = 0.0
            flags.append("NO_PREVIOUS_STATE")
        else:
            weak = min(1.0, prev.get("DETERIORATING", 0.0) + r.recovery_carry * prev.get("RECOVERY", 0.0))
        raw = {"GROWTH": (1 - weak) * (1 - det) * g_hi, "STABLE": (1 - weak) * (1 - det) * (1 - g_hi),
               "DETERIORATING": det, "RECOVERY": weak * (1 - det)}
        assert set(raw) == set(FUNDAMENTAL_STATES)
        p = self._merge(raw)
        return PeriodPosterior(period_end=row.period_end, probabilities=p,
                               memberships={"growth_high": g_hi, "contraction": g_neg, "margin_compression": m_down,
                                            "deteriorating": det, "weak_prior_state": weak},
                               argmax=max(p, key=p.get), entropy=_entropy(p), flags=sorted(flags + row.flags))

    def filter(self, rows: Sequence[FeatureRow]) -> list[PeriodPosterior]:
        out: list[PeriodPosterior] = []
        prev: dict[str, float] | None = None
        for row in sorted(rows, key=lambda r: r.period_end):
            pp = self.classify_period(row, prev)
            out.append(pp)
            prev = pp.probabilities
        return out

    def current(self, history: Sequence[PeriodPosterior], as_of: datetime) -> FundamentalRegimePosterior:
        a = cite("REGIME-RULES-v1", "REGIME-PIT-FUNDAMENTALS-ONLY-v1")
        if not history:
            u = 1.0 / len(self.states)
            return FundamentalRegimePosterior(
                model_id=self.model_id, model_version=self.model_version, states=self.states,
                probabilities={s: u for s in self.states}, period_end=None, as_of=as_of, staleness_days=None,
                flags=["NO_FEATURES_UNIFORM_PRIOR", "LOW_CONFIDENCE"], assumptions=a)
        last = history[-1]
        flags = list(last.flags)
        if len(history) < 2:
            flags.append("LOW_CONFIDENCE")
        return FundamentalRegimePosterior(
            model_id=self.model_id, model_version=self.model_version, states=self.states,
            probabilities=dict(last.probabilities), period_end=last.period_end, as_of=as_of,
            staleness_days=(local_date(as_of) - last.period_end).days, flags=sorted(set(flags)), assumptions=a)
