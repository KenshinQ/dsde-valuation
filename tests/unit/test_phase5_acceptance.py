"""VMS-0.2 Phase 5 acceptance (SPEC §20 Phase 5 / §12.5–12.6 / §12.8 / §24)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from vms.methods import MethodConfig, build_registry_from_config
from vms.methods.multiples import (
    METRIC_DEFINITIONS,
    aggregate_multiples,
    apply_equity_multiple,
    apply_ev_multiple,
    build_peer_set,
    check_denominator,
    get_definition,
    run_eligible_multiple_methods,
)
from vms.methods.protocol import ValuationContext
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.schemas.config import load_config
from vms.schemas.contracts import MethodEligibilityStatus, ProfileFlag, ProfileLabel, ValuationTarget
from vms.schemas.observations import PeerObservation, QualityStatus

CST = timezone(timedelta(hours=8))
ASOF = datetime(2025, 6, 30, 15, tzinfo=CST)
SUBJ = "SYNTH.TEST"


def _peer(pid: str, field: str, value: float, *, published="2022-01-15T09:00:00",
          start=date(2021, 1, 1), metric_ts="2025-06-30T15:00:00", **kw) -> PeerObservation:
    return PeerObservation(
        subject_instrument_id=SUBJ,
        peer_instrument_id=pid,
        published_at=datetime.fromisoformat(published).replace(tzinfo=CST),
        membership_start=start,
        membership_end=kw.get("end"),
        field_name=field,
        value=value,
        currency="CNY",
        unit_scale="unit",
        metric_timestamp=datetime.fromisoformat(metric_ts).replace(tzinfo=CST),
        source_id="SYNTHETIC",
        revision_id="r0",
        quality_status=QualityStatus.OBSERVED,
    )


def _peers_for(field: str, values: list[float]) -> list[PeerObservation]:
    return [_peer(f"P{i}.SZ", field, v) for i, v in enumerate(values)]


def _mature_ctx(repo, *, subject=None, peers=None, target=ValuationTarget.RELATIVE_VALUE_CURRENT,
                flags=None, primary=None):
    loaded = load_config(repo / "config/default.yaml")
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    feats = features_from_fixture(data)
    feats = feats.model_copy(update={"instrument_id": SUBJ, "as_of": "2025-06-30"})
    profile = classify_profile(feats)
    if flags or primary:
        upd = {}
        if flags is not None:
            upd["flags"] = list(flags)
        if primary is not None:
            upd["primary_profile"] = primary
        profile = profile.model_copy(update=upd)
    fields = frozenset(data.get("available_fields") or []) | {
        "parent_net_income", "total_equity", "ebit", "depreciation_amortization",
        "revenue", "interest_bearing_debt", "cash",
    }
    sm = subject or {
        "parent_net_income": 100.0, "total_equity": 500.0, "ebit": 140.0,
        "ebitda": 160.0, "depreciation_amortization": 20.0, "revenue": 1000.0,
        "cash": 50.0, "interest_bearing_debt": 120.0, "diluted_shares": 10.0,
    }
    return loaded, ValuationContext(
        instrument_id=SUBJ, as_of=ASOF.isoformat(), target=target, profile=profile,
        available_fields=fields, peer_count=len({p.peer_instrument_id for p in (peers or [])}),
        loaded=loaded, subject_metrics=sm, peer_observations=tuple(peers or []),
    )


# ---- AC1: metric definition / denominator / bridge explicit ----
def test_ac1_each_metric_definition_denominator_and_bridge_explicit():
    assert set(METRIC_DEFINITIONS) == {"pe", "pb", "ev_ebit", "ev_ebitda", "ev_sales"}
    pe = get_definition("pe")
    assert pe.denominator_field == "parent_net_income"
    assert pe.applies_ev_bridge is False
    assert "EquityValue" in pe.formula
    pb = get_definition("pb")
    assert pb.denominator_field == "total_equity" and pb.applies_ev_bridge is False
    for mid in ("ev_ebit", "ev_ebitda", "ev_sales"):
        d = get_definition(mid)
        assert d.applies_ev_bridge is True
        assert "bridge" in d.formula.lower() or "EV" in d.formula
    assert get_definition("ev_sales").value_claim.value == "RELATIVE_PRICING_ONLY"


# ---- AC2: negative / near-zero denominators ----
def test_ac2_negative_near_zero_denominator_exclusions(repo):
    assert check_denominator(field="parent_net_income", value=-10.0).ok is False
    assert check_denominator(field="parent_net_income", value=-10.0).code == "INELIGIBLE_DENOMINATOR"
    assert check_denominator(field="ebit", value=1e-9, near_zero_eps=1e-6).ok is False
    assert check_denominator(field="revenue", value=0.0).ok is False

    peers = _peers_for("pe", [12, 13, 14, 15, 16, 17, 18, 19])
    loaded, ctx = _mature_ctx(repo, subject={"parent_net_income": -50.0, "diluted_shares": 10.0}, peers=peers)
    plugin = build_registry_from_config(loaded.method_registry).plugin("pe")
    res = plugin.value_paths(ctx, None, MethodConfig(method_id="pe"))
    assert res.status is MethodEligibilityStatus.INELIGIBLE
    assert "INELIGIBLE_DENOMINATOR" in res.reason_codes
    assert res.values == {}


# ---- AC3 + AC4: PIT peers + persisted exclusions ----
def test_ac3_ac4_pit_peer_membership_and_persisted_exclusions():
    peers = [
        _peer("KEEP.SZ", "pe", 12.0),
        _peer("FUTURE_PUB.SZ", "pe", 50.0, published="2026-01-01T09:00:00"),
        _peer("JOIN_LATER.SZ", "pe", 40.0, start=date(2026, 1, 1)),
        _peer("FUTURE_METRIC.SZ", "pe", 30.0, metric_ts="2025-07-01T15:00:00"),
        _peer("WRONG_METRIC.SZ", "pb", 2.0),
        _peer("NEG.SZ", "pe", -3.0),
    ]
    report = build_peer_set(
        subject_instrument_id=SUBJ, as_of=ASOF, metric_field="pe", peers=peers,
    )
    assert [i.peer_instrument_id for i in report.included] == ["KEEP.SZ"]
    reasons = {e.peer_instrument_id: e.reasons for e in report.excluded}
    assert "PIT_PUBLISHED_AFTER_ASOF" in reasons["FUTURE_PUB.SZ"]
    assert "PIT_MEMBERSHIP_START_AFTER_ASOF" in reasons["JOIN_LATER.SZ"]
    assert "PIT_METRIC_TIMESTAMP_AFTER_ASOF" in reasons["FUTURE_METRIC.SZ"]
    assert any("METRIC_FIELD_MISMATCH" in r for r in reasons["WRONG_METRIC.SZ"])
    assert "NONPOSITIVE_OR_NONFINITE_MULTIPLE" in reasons["NEG.SZ"]
    # Persistable
    dumped = report.model_dump(mode="json")
    assert dumped["n_included"] == 1 and dumped["excluded"]


def test_ac3_future_peer_cannot_enter_historical_sample_via_method(repo):
    """Leakage: adding a post-as_of peer must not change the multiple used."""
    base_peers = _peers_for("pe", [10, 11, 12, 13, 14, 15, 16, 17])
    future = _peer("LEAK.SZ", "pe", 1000.0, published="2026-02-01T09:00:00", metric_ts="2026-02-01T15:00:00")
    loaded, ctx1 = _mature_ctx(repo, peers=base_peers)
    _, ctx2 = _mature_ctx(repo, peers=base_peers + [future])
    reg = build_registry_from_config(loaded.method_registry)
    r1 = reg.plugin("pe").value_paths(ctx1, None, MethodConfig(method_id="pe"))
    r2 = reg.plugin("pe").value_paths(ctx2, None, MethodConfig(method_id="pe"))
    assert r1.values["multiple_used"] == r2.values["multiple_used"]
    excl_ids = {e["peer_instrument_id"] for e in r2.diagnostics["peer_set"]["excluded"]}
    assert "LEAK.SZ" in excl_ids


# ---- AC5: outliers / small sample diagnostics ----
def test_ac5_outliers_and_small_sample_diagnostics():
    # Small sample
    small = aggregate_multiples([10.0, 11.0, 12.0], peer_min_count=5)
    assert small.ok is False
    assert "PEER_SCARCITY" in small.flags and "PEER_DATA_INSUFFICIENT" in small.flags

    # High dispersion
    wide = aggregate_multiples([5.0, 6.0, 7.0, 8.0, 9.0, 50.0, 60.0, 70.0],
                               peer_min_count=5, max_dispersion_ratio=0.5)
    assert "HIGH_PEER_DISPERSION" in wide.flags

    # Robust vs blind mean: outlier should not dominate median
    vals = [10, 11, 12, 13, 14, 15, 16, 1000]
    med = aggregate_multiples(vals, estimator="median", peer_min_count=5)
    assert med.ok and med.multiple == pytest.approx(13.5, abs=1.0)
    assert med.multiple < 50  # not pulled to blind mean ~136


# ---- AC6: no cross-bridge / double-count ----
def test_ac6_equity_methods_no_ev_bridge_ev_methods_bridge_once(repo):
    pe_def = get_definition("pe")
    ev_def = get_definition("ev_ebit")
    eq = apply_equity_multiple(definition=pe_def, multiple=15.0, denominator=100.0, diluted_shares=10.0)
    assert eq.valid and eq.ev_bridge_applied is False and eq.enterprise_value is None
    assert eq.equity_value == pytest.approx(1500.0)
    assert eq.value_per_share == pytest.approx(150.0)

    ev = apply_ev_multiple(
        definition=ev_def, multiple=10.0, denominator=140.0,
        cash=50.0, debt=120.0, diluted_shares=10.0,
    )
    assert ev.valid and ev.ev_bridge_applied is True
    assert ev.enterprise_value == pytest.approx(1400.0)
    # Equity = 1400 + 50 - 120 = 1330
    assert ev.equity_value == pytest.approx(1330.0)
    assert ev.bridge is not None

    # Cross-application rejected
    bad = apply_equity_multiple(definition=ev_def, multiple=10.0, denominator=140.0, diluted_shares=10.0)
    assert bad.valid is False and bad.invalid_reason == "BRIDGE_CONTRACT_MISMATCH"

    # Through plugin: pe has ev_bridge_applied False; ev_ebit True
    peers_pe = _peers_for("pe", [12, 13, 14, 15, 16, 17, 18, 19])
    peers_ev = _peers_for("ev_ebit", [9, 10, 11, 12, 10.5, 11.5, 9.5, 12.5])
    loaded, ctx_pe = _mature_ctx(repo, peers=peers_pe)
    _, ctx_ev = _mature_ctx(repo, peers=peers_ev)
    reg = build_registry_from_config(loaded.method_registry)
    r_pe = reg.plugin("pe").value_paths(ctx_pe, None, MethodConfig(method_id="pe"))
    r_ev = reg.plugin("ev_ebit").value_paths(ctx_ev, None, MethodConfig(method_id="ev_ebit"))
    assert r_pe.values["ev_bridge_applied"] is False
    assert r_ev.values["ev_bridge_applied"] is True
    assert r_ev.values["bridge"] is not None


def test_ev_sales_labeled_relative_pricing_not_intrinsic(repo):
    peers = _peers_for("ev_sales", [1.5, 1.8, 2.0, 2.2, 2.4, 1.9, 2.1, 2.3])
    loaded, ctx = _mature_ctx(repo, peers=peers)
    # Negative earnings subject still ok for sales multiple
    ctx = ctx.model_copy(update={"subject_metrics": {
        **ctx.subject_metrics, "parent_net_income": -10.0, "revenue": 1000.0,
    }})
    r = build_registry_from_config(loaded.method_registry).plugin("ev_sales").value_paths(
        ctx, None, MethodConfig(method_id="ev_sales"),
    )
    assert r.values
    assert r.values["value_claim"] == "RELATIVE_PRICING_ONLY"
    assert "RELATIVE_PRICING_NOT_INTRINSIC" in r.values["flags"]


def test_cyclical_trailing_without_midcycle_flagged(repo):
    peers = _peers_for("pe", [10, 11, 12, 13, 14, 15, 16, 17])
    loaded, ctx = _mature_ctx(
        repo, peers=peers,
        primary=ProfileLabel.CYCLICAL_OPERATING,
        flags=[ProfileFlag.HIGH_CYCLICALITY],
    )
    r = build_registry_from_config(loaded.method_registry).plugin("pe").value_paths(
        ctx, None, MethodConfig(method_id="pe"),
    )
    assert r.values
    assert "CYCLE_ESTIMATE_LOW_CONFIDENCE" in r.values["flags"]
    assert r.status is MethodEligibilityStatus.LOW_CONFIDENCE


def test_cyclical_low_shrink_denom_not_injected_into_mid(repo):
    """LOW sector-prior shrink must not inject into production mid (PR#22 SF2).

    Cyclical + stub+prior + short incomplete series → estimator returns a
    positive research-only denom at LOW; Phase5 HIGH∧denom>0 gate must keep
    trailing (no MID_CYCLE_DENOMINATOR_USED). Gate in common.py unchanged.
    """
    short_series = [(date(2020 + i, 12, 31), 10.0 + i) for i in range(3)]
    peers = _peers_for("pe", [10, 11, 12, 13, 14, 15, 16, 17])
    loaded, ctx = _mature_ctx(
        repo,
        peers=peers,
        primary=ProfileLabel.CYCLICAL_OPERATING,
        flags=[ProfileFlag.HIGH_CYCLICALITY],
        subject={
            "parent_net_income": 100.0,
            "total_equity": 500.0,
            "ebit": 140.0,
            "ebitda": 160.0,
            "depreciation_amortization": 20.0,
            "revenue": 1000.0,
            "cash": 50.0,
            "interest_bearing_debt": 120.0,
            "diluted_shares": 10.0,
            "pit_parent_net_income_series": short_series,
        },
    )
    r = build_registry_from_config(loaded.method_registry).plugin("pe").value_paths(
        ctx,
        None,
        MethodConfig(
            method_id="pe",
            assumptions={
                "use_sector_prior_stub": True,
                "sector_prior_mid_cycle": 50.0,
            },
        ),
    )
    assert r.values
    assert "MID_CYCLE_DENOMINATOR_USED" not in r.values["flags"]
    assert "CYCLE_ESTIMATE_LOW_CONFIDENCE" in r.values["flags"]
    assert r.values["denominator_value"] == pytest.approx(100.0)  # trailing
    assert r.status is MethodEligibilityStatus.LOW_CONFIDENCE
    est = (r.diagnostics or {}).get("midcycle_estimate")
    assert est is not None
    assert est["confidence"] == "LOW"
    assert est["mid_cycle_denominator"] is not None
    assert est["mid_cycle_denominator"] > 0
    assert est["diagnostics"]["research_only"] is True
    assert est["diagnostics"]["sector_prior_applied"] is True
    assert "SECTOR_PRIOR_SHRINK_APPLIED" in est["diagnostics"]["reason_codes"]


def test_hand_fixture_pe_equity_and_ev_ebit_bridge(repo):
    """Hand calc: peers median 14; NI=100 → equity 1400; EV/EBIT median 10 × 140 → EV 1400 → eq 1330."""
    peers = (
        _peers_for("pe", [12, 13, 14, 14, 15, 16, 17, 11])
        + _peers_for("ev_ebit", [9, 10, 10, 11, 10, 10, 12, 8])
    )
    loaded, ctx = _mature_ctx(repo, peers=peers)
    reg = build_registry_from_config(loaded.method_registry)
    pe = reg.plugin("pe").value_paths(ctx, None, MethodConfig(method_id="pe"))
    assert pe.values["multiple_used"] == pytest.approx(14.0)
    assert pe.values["equity_value"] == pytest.approx(1400.0)
    assert pe.values["value_per_share"] == pytest.approx(140.0)

    ev = reg.plugin("ev_ebit").value_paths(ctx, None, MethodConfig(method_id="ev_ebit"))
    assert ev.values["multiple_used"] == pytest.approx(10.0)
    assert ev.values["enterprise_value"] == pytest.approx(1400.0)
    assert ev.values["equity_value"] == pytest.approx(1330.0)  # 1400+50-120


def test_run_eligible_multiples_no_ensemble(repo):
    peers = []
    for field, vals in {
        "pe": [12, 13, 14, 15, 16, 17, 18, 19],
        "pb": [1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2],
        "ev_ebit": [9, 10, 11, 12, 10, 11, 9, 12],
        "ev_ebitda": [7, 8, 9, 8, 7.5, 8.5, 9.5, 8.2],
        "ev_sales": [1.8, 2.0, 2.2, 1.9, 2.1, 2.3, 2.0, 1.7],
    }.items():
        peers.extend(_peers_for(field, vals))
    loaded, ctx = _mature_ctx(repo, peers=peers)
    bundle = run_eligible_multiple_methods(
        registry=build_registry_from_config(loaded.method_registry),
        profile=ctx.profile,
        target=ValuationTarget.RELATIVE_VALUE_CURRENT,
        loaded=loaded,
        available_fields=ctx.available_fields,
        subject_metrics=ctx.subject_metrics,
        peer_observations=list(peers),
        as_of=ctx.as_of,
    )
    assert bundle.ensemble is None
    assert bundle.investment_value == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert set(bundle.eligible_run) >= {"pe", "pb", "ev_ebit", "ev_ebitda", "ev_sales"}
    assert bundle.peer_diagnostics
