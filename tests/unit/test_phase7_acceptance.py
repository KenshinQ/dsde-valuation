"""VMS-0.2 Phase 7 acceptance (SPEC §20 Phase 7 / §11.3–11.4 / §13 / §24)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.methods import MethodResult, build_registry_from_config
from vms.methods.protocol import ValuationContext
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.router import (
    SUITABILITY_DIMENSIONS,
    check_combination_compatibility,
    compare_methods,
    method_eligibility_payload,
    refuse_uncalibrated_blend,
    route_methods,
)
from vms.router.suitability import SoftSuitability, compute_soft_suitability
from vms.schemas.config import load_config
from vms.schemas.contracts import (
    ClaimStatus,
    MethodEligibilityStatus,
    OutputBasis,
    ValuationTarget,
)


@pytest.fixture
def repo() -> Path:
    return Path(__file__).resolve().parents[2]


def _mature(repo: Path):
    loaded = load_config(repo / "config/default.yaml")
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    profile = classify_profile(features_from_fixture(data))
    return loaded, profile, frozenset(data.get("available_fields") or [])


# ---- AC1: Router logs every considered method, hard-gate, scores, runnable, reason ----
def test_ac1_router_logs_considerations(repo):
    loaded, profile, fields = _mature(repo)
    registry = build_registry_from_config(loaded.method_registry)
    report = route_methods(
        registry=registry,
        profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        available_fields=fields,
        peer_count=8,
    )
    assert report.considerations, "must log considerations"
    assert len(report.considerations) == len(report.candidates)
    assert report.candidates == sorted(report.candidates), "deterministic candidate order"
    for c in report.considerations:
        assert c.considered is True
        assert c.hard_gate_reasons, f"{c.method_id} missing hard_gate_reasons"
        assert c.reason
        assert c.status in MethodEligibilityStatus
        if c.hard_gate_passed:
            assert c.selected_runnable is True
            assert c.soft_suitability is not None
            dims = c.soft_suitability.as_dict()
            assert set(dims) == set(SUITABILITY_DIMENSIONS)
            assert c.soft_suitability.ensemble_weight is None
            # No opaque single score field on SoftSuitability
            assert not hasattr(c.soft_suitability, "score") or getattr(c.soft_suitability, "score", None) is None
        else:
            assert c.selected_runnable is False
            assert c.soft_suitability is None

    payload = method_eligibility_payload(report, run_id="test")
    assert "methods" in payload and len(payload["methods"]) == len(report.considerations)


# ---- AC2: Same context/config → same route ----
def test_ac2_routing_deterministic(repo):
    loaded, profile, fields = _mature(repo)
    registry = build_registry_from_config(loaded.method_registry)
    kwargs = dict(
        registry=registry,
        profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        available_fields=fields,
        peer_count=8,
    )
    r1 = route_methods(**kwargs)
    r2 = route_methods(**kwargs)
    assert r1.model_dump(mode="json") == r2.model_dump(mode="json")
    assert r1.routing_deterministic is True


# ---- AC3: Incompatible target/horizon/output basis cannot be combined ----
def test_ac3_incompatible_cannot_combine():
    ev_only = MethodResult(
        method_id="ev_only",
        status=MethodEligibilityStatus.VALID,
        output_basis=[OutputBasis.EV],
        values={"enterprise_value": {"p50": 100.0}},
    )
    equity = MethodResult(
        method_id="equity_m",
        status=MethodEligibilityStatus.VALID,
        output_basis=[OutputBasis.EQUITY],
        values={"equity_value": {"p50": 80.0}},
    )
    compat = check_combination_compatibility(
        [ev_only, equity],
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        horizon=None,
        requested_output_basis=OutputBasis.EQUITY,
    )
    assert compat.compatible is False
    assert any(i.code == "EV_EQUITY_BRIDGE_REQUIRED" for i in compat.issues)

    # Horizon mismatch
    a = MethodResult(
        method_id="a", status=MethodEligibilityStatus.VALID,
        output_basis=[OutputBasis.EQUITY], values={"equity_value": 10.0},
    )
    b = MethodResult(
        method_id="b", status=MethodEligibilityStatus.VALID,
        output_basis=[OutputBasis.EQUITY], values={"equity_value": 12.0},
    )
    compat_h = check_combination_compatibility(
        [a, b],
        target=ValuationTarget.FUNDAMENTAL_VALUE_HORIZON,
        horizon=3,
        requested_output_basis=OutputBasis.EQUITY,
        result_horizons={"a": 3, "b": 5},
    )
    assert compat_h.compatible is False
    assert any(i.code == "HORIZON_MISMATCH" for i in compat_h.issues)

    # Intrinsic vs market exit price
    mkt = MethodResult(
        method_id="exit", status=MethodEligibilityStatus.VALID,
        output_basis=[OutputBasis.MARKET_PRICE], values={"exit_price": 50.0},
    )
    compat_m = check_combination_compatibility(
        [equity, mkt],
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        requested_output_basis=OutputBasis.EQUITY,
        result_targets={
            "equity_m": ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
            "exit": ValuationTarget.MARKET_EXIT_PRICE,
        },
    )
    assert compat_m.compatible is False
    assert any(i.code == "INTRINSIC_VS_MARKET_PRICE" for i in compat_m.issues)

    refusal = refuse_uncalibrated_blend(
        [a, b],
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        requested_output_basis=OutputBasis.EQUITY,
    )
    assert refusal["combined_value"] is None
    assert refusal["status"] == ClaimStatus.ENSEMBLE_UNCALIBRATED.value


# ---- AC4: Method results retain identity after normalization ----
def test_ac4_normalization_retains_identity():
    results = [
        MethodResult(
            method_id="fcff_dcf",
            status=MethodEligibilityStatus.VALID,
            output_basis=[OutputBasis.EQUITY],
            values={"equity_value": {"p50": 1000.0, "mean": 1100.0}},
        ),
        MethodResult(
            method_id="ddm",
            status=MethodEligibilityStatus.VALID,
            output_basis=[OutputBasis.EQUITY],
            values={"equity_value": {"p50": 700.0}},
        ),
    ]
    report = compare_methods(
        results,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        requested_output_basis=OutputBasis.EQUITY,
        request_blend=True,
    )
    ids = [n.method_id for n in report.normalized]
    assert ids == ["ddm", "fcff_dcf"]  # sorted, identity preserved
    assert all(n.retained_identity for n in report.normalized)
    assert report.disagreement.n_methods == 2
    assert report.disagreement.range == pytest.approx(300.0)
    assert report.ensemble["combined_value"] is None
    assert report.ensemble["status"] == ClaimStatus.ENSEMBLE_UNCALIBRATED.value
    # Suitability must not appear as mixture weights
    assert report.ensemble.get("mixture_weights") is None


# ---- AC5: No eligible method → INSUFFICIENT_METHOD_COVERAGE, not default DCF ----
def test_ac5_no_eligible_returns_insufficient_coverage_not_default_dcf(repo):
    loaded, profile, _fields = _mature(repo)
    registry = build_registry_from_config(loaded.method_registry)
    report = route_methods(
        registry=registry,
        profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        available_fields=frozenset(),  # strip all fields
        peer_count=0,
    )
    assert report.coverage_status == "INSUFFICIENT_METHOD_COVERAGE"
    assert all(not c.selected_runnable for c in report.considerations)
    assert all(not e.eligible for e in report.eligibility)
    # Must not invent a default FCFF runnable
    fcff = next(c for c in report.considerations if c.method_id == "fcff_dcf")
    assert fcff.selected_runnable is False
    assert fcff.hard_gate_passed is False
    assert "not defaulting to DCF" in report.notes


def test_soft_suitability_requires_all_dimensions_no_opaque_score(repo):
    loaded, profile, fields = _mature(repo)
    entry = next(e for e in loaded.method_registry.methods if e.method_id == "fcff_dcf")
    ctx = ValuationContext(
        instrument_id=profile.instrument_id,
        as_of=profile.as_of,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        profile=profile,
        available_fields=fields,
        peer_count=8,
    )
    soft = compute_soft_suitability(entry, ctx, hard_gate_passed=True)
    assert soft is not None
    assert set(soft.dimensions) == set(SUITABILITY_DIMENSIONS)
    assert soft.ensemble_weight is None
    assert soft.dimensions["calibration_evidence"] == 0.0
    # Incomplete vector rejected
    with pytest.raises(Exception):
        SoftSuitability(dimensions={"conceptual_fit": 0.5}, rationales={})
    # Soft not computed when hard gates fail
    assert compute_soft_suitability(entry, ctx, hard_gate_passed=False) is None


def test_schema_version_tracks_current_phase_contract():
    assert SCHEMA_VERSION == "vms-0.2.phase12"
    assert IMPLEMENTED_PHASE == "PHASE_12"
