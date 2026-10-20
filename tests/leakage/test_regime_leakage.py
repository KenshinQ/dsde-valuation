"""Phase 3 leakage tests: regime inference sees PIT fundamentals only (no prices, no returns, nothing after as_of),
and walk-forward origins see only data published by the origin (SPEC §7.4, §18 Phase 3)."""

from __future__ import annotations

import ast
import copy
import inspect
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.company import CST, cyclical_company, loaded_config
from tests.factories import INST, fobs, mobs
from vms.pipeline import run_estimation
from vms.pit.snapshot import build_snapshot
from vms.regimes import infer_regimes

L = loaded_config()
RC = L.config.regimes
REG_DIR = Path(inspect.getfile(infer_regimes)).parent
FORBIDDEN = ("price", "close", "return", "adjusted", "market_cap", "volume", "pitsnapshot", "snapshotmarket")


def test_regime_code_cannot_reference_prices_or_returns():
    """Static check: regime inference modules contain no price/return identifiers and never touch `.market`."""
    for p in sorted(REG_DIR.glob("*.py")):
        if p.name in ("market.py", "schemas.py"):      # market-regime placeholder + pure schemas
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        # the only allowed `market` name: the RegimeResult field holding the separate (UNAVAILABLE) market schema
        fields = {n.target.id for n in ast.walk(tree) if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
        allowed = {"market"} & fields if p.name == "__init__.py" else set()
        for node in ast.walk(tree):
            ident = (node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute)
                     else node.arg if isinstance(node, ast.arg) else None)
            if ident is not None:
                low = ident.lower()
                assert not any(f in low for f in FORBIDDEN), f"{p.name}: forbidden identifier {ident!r}"
                assert ident != "market" or ident in allowed, f"{p.name}: accesses market data"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", None) or ""
                names = {a.name for a in node.names}
                assert "MarketObservation" not in names and "SnapshotMarket" not in names, p.name
                assert not mod.startswith(("vms.data", "vms.drivers", "vms.statements", "vms.quality")), (p.name, mod)


def test_infer_regimes_signature_is_fundamentals_only():
    assert list(inspect.signature(infer_regimes).parameters) == ["financials", "as_of", "cfg"]


@pytest.fixture(scope="module")
def base():
    load, as_of = cyclical_company()
    return load, as_of, run_estimation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=5)


def _regime_dump(r):
    return (r.regimes.current.model_dump(mode="json"), [h.model_dump(mode="json") for h in r.regimes.history],
            r.regimes.transitions.model_dump(mode="json"), r.regimes.next_year)


@settings(max_examples=8, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(factors=st.lists(st.floats(0.3, 3.0), min_size=1, max_size=40))
def test_prices_cannot_change_regimes_or_distributions(base, factors):
    load, as_of, r0 = base
    load2 = copy.copy(load)
    load2.market = [m.model_copy(update={"raw_close": m.raw_close * factors[i % len(factors)]})
                    for i, m in enumerate(load.market)]
    r = run_estimation(load2, instrument_id=INST, as_of=as_of, loaded=L, seed=5)
    assert _regime_dump(r) == _regime_dump(r0)
    assert r.distributions == r0.distributions and r.walk_forward == r0.walk_forward


def test_future_prices_and_fundamentals_invisible(base):
    """Rows after as_of (a price crash, a huge restatement of FY2024, FY2025 results) change nothing."""
    load, as_of, r0 = base
    load2 = copy.copy(load)
    later = (as_of + timedelta(days=3)).date().isoformat()
    load2.market = [*load.market, mobs(later, 0.5, shares=1e3),
                    mobs((as_of + timedelta(days=90)).date().isoformat(), 100.0, shares=1e3)]
    load2.financial = [*load.financial,
                       fobs("2024-12-31", "revenue", 1.0, later, rev="r9"),
                       fobs("2024-12-31", "ebit", -500.0, later, rev="r9"),
                       fobs("2025-03-31", "revenue", 9e9, later)]
    r = run_estimation(load2, instrument_id=INST, as_of=as_of, loaded=L, seed=5)
    assert _regime_dump(r) == _regime_dump(r0)
    assert r.distributions == r0.distributions and r.walk_forward == r0.walk_forward
    assert all(f.known_at <= as_of for f in r.regimes.features)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(days=st.integers(0, 16 * 366))
def test_regimes_full_vs_known_only(base, days):
    load, _, _ = base
    as_of = datetime(2010, 1, 1, 15, tzinfo=CST) + timedelta(days=days)

    def regimes(fin):
        snap, _, _ = build_snapshot(instrument_id=INST, as_of=as_of, financial=fin, market=[], corporate_actions=[],
                                    sources=load.sources)
        r = infer_regimes(snap.financials, as_of=as_of, cfg=RC)
        return r, (r.current.model_dump(mode="json"), [h.model_dump(mode="json") for h in r.history],
                   r.transitions.model_dump(mode="json"))

    full, a = regimes(load.financial)
    _, b = regimes([o for o in load.financial if o.published_at <= as_of])
    assert a == b
    assert all(f.known_at <= as_of for f in full.features)
    assert all(h.period_end <= as_of.date() for h in full.history)


def test_walk_forward_origin_unaffected_by_post_origin_mutation(base):
    """Mutate everything published after one origin: that origin's forecasts must not move."""
    load, as_of, r0 = base
    origin = next(o for o in r0.walk_forward.origins if o.origin_year == 2016)
    load2 = copy.copy(load)
    load2.financial = [o.model_copy(update={"value": o.value * 1.7})
                       if (o.published_at > origin.origin_as_of and o.value is not None) else o
                       for o in load.financial]
    r = run_estimation(load2, instrument_id=INST, as_of=as_of, loaded=L, seed=5)
    o2 = next(o for o in r.walk_forward.origins if o.origin_year == 2016)
    assert o2.train_years == origin.train_years and max(o2.train_years) <= 2016
    for name, d in origin.drivers.items():
        assert o2.drivers[name]["forecast_quantiles"] == d["forecast_quantiles"], name
    assert o2.regime["forecast"] == origin.regime["forecast"]
