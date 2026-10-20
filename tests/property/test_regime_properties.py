"""Posterior probabilities are finite, non-negative and sum to one (SPEC §19 property tests)."""

import math
from datetime import date, datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.company import loaded_config
from vms.regimes import FeatureRow, estimate_transitions, propagate
from vms.regimes.rule_based import RuleBasedClassifier
from vms.schemas.config import FUNDAMENTAL_STATES

RC = loaded_config().config.regimes
CST = timezone(timedelta(hours=8))
feat = st.one_of(st.none(), st.floats(-5, 5, allow_nan=False))
subsets = st.sets(st.sampled_from(["GROWTH", "DETERIORATING", "RECOVERY"])).map(
    lambda s: [x for x in FUNDAMENTAL_STATES if x in s or x == "STABLE"])
rules = st.fixed_dictionaries({"growth_high": st.floats(0.01, 0.5), "growth_low": st.floats(-0.5, 0.0),
                               "tau_growth": st.floats(1e-4, 1.0), "margin_band": st.floats(0, 0.1),
                               "tau_margin": st.floats(1e-5, 0.5), "recovery_carry": st.floats(0, 1)})


def _ok(p, states):
    assert list(p) == states
    assert all(math.isfinite(v) and v >= 0 for v in p.values())
    assert abs(sum(p.values()) - 1) <= 1e-9


@settings(max_examples=300, deadline=None)
@given(seq=st.lists(st.tuples(feat, feat), min_size=1, max_size=30), states=subsets, r=rules)
def test_filtered_posteriors_are_probabilities(seq, states, r):
    cfg = RC.model_copy(update={"states": states, "rules": RC.rules.model_copy(update=r)})
    clf = RuleBasedClassifier(cfg)
    rows = [FeatureRow(period_end=date(1990 + i, 12, 31), cadence="annual", revenue_growth_yoy=g, ebit_margin_ttm=None,
                       ebit_margin_change_yoy=dm, known_at=datetime(1991 + i, 4, 1, tzinfo=CST), refs=[], flags=[])
            for i, (g, dm) in enumerate(seq) if not (g is None and dm is None)]
    hist = clf.filter(rows)
    for h in hist:
        _ok(h.probabilities, states)
        assert h.entropy >= -1e-12
    cur = clf.current(hist, datetime(2030, 1, 1, tzinfo=CST))
    _ok(cur.probabilities, states)
    tm = estimate_transitions(hist, cfg, "annual")
    for row in tm.mean:
        assert all(math.isfinite(x) and x >= 0 for x in row) and abs(sum(row) - 1) <= 1e-9
    _ok(propagate(cur.probabilities, tm), states)
