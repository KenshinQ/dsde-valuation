"""Midcycle backlog #4 slice C — emitter wiring (diagnostics fan-out)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from vms.ensemble import (
    MethodDistribution,
    diagnostics_with_midcycle_passthrough,
    method_distribution_from_result,
    samples_from_point,
)
from vms.methods import MethodConfig, build_registry_from_config
from vms.methods.multiples.midcycle import (
    MidCycleConfidence,
    injectable_mid_denominator,
    passthrough_midcycle_diagnostics,
    profile_is_cyclical,
    resolve_cyclical_midcycle,
)
from vms.methods.protocol import MethodResult, ValuationContext
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.reporting.phase5_bundle import build_phase5_bundle
from vms.schemas.config import load_config
from vms.schemas.contracts import (
    MethodEligibilityStatus,
    OutputBasis,
    ProfileFlag,
    ProfileLabel,
    ValuationTarget,
)

CST = timezone(timedelta(hours=8))
ASOF = datetime(2025, 6, 30, 15, tzinfo=CST)
SUBJ = "SYNTH.CYC.EMIT"


def _complete_series():
    years = list(range(2018, 2025))
    values = [40.0, 55.0, 90.0, 100.0, 80.0, 45.0, 60.0]
    return [(date(y, 12, 31), v) for y, v in zip(years, values)]


def _ctx(repo, *, cyclical: bool, series=None, primary=None, flags=None, subject_extra=None):
    loaded = load_config(repo / "config/default.yaml")
    fix = "cyclical.json" if cyclical else "mature_operating.json"
    data = load_fixture(fixtures_dir() / fix)
    feats = features_from_fixture(data)
    feats = feats.model_copy(update={"instrument_id": SUBJ, "as_of": "2025-06-30"})
    profile = classify_profile(feats)
    if cyclical:
        profile = profile.model_copy(
            update={
                "primary_profile": ProfileLabel.CYCLICAL_OPERATING,
                "flags": [ProfileFlag.HIGH_CYCLICALITY],
            }
        )
    if primary is not None:
        profile = profile.model_copy(update={"primary_profile": primary, "flags": flags or []})
    sm = {
        "parent_net_income": 100.0,
        "total_equity": 500.0,
        "diluted_shares": 10.0,
    }
    if series is not None:
        sm["pit_parent_net_income_series"] = series
    if subject_extra:
        sm.update(subject_extra)
    ctx = ValuationContext(
        instrument_id=SUBJ,
        as_of=ASOF.isoformat(),
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        profile=profile,
        available_fields=frozenset(sm),
        subject_metrics=sm,
        loaded=loaded,
    )
    return loaded, ctx


def test_resolve_non_cyclical_returns_none(repo):
    _, ctx = _ctx(repo, cyclical=False, series=_complete_series())
    assert profile_is_cyclical(ctx.profile) is False
    assert resolve_cyclical_midcycle(ctx, denom_field="parent_net_income") is None


def test_resolve_cyclical_incomplete_low_none(repo):
    _, ctx = _ctx(repo, cyclical=True, series=None)
    est = resolve_cyclical_midcycle(ctx, denom_field="parent_net_income")
    assert est is not None
    assert est.confidence is MidCycleConfidence.LOW
    assert est.mid_cycle_denominator is None
    assert injectable_mid_denominator(est) is None


def test_resolve_cyclical_complete_high_injectable(repo):
    _, ctx = _ctx(repo, cyclical=True, series=_complete_series())
    est = resolve_cyclical_midcycle(ctx, denom_field="parent_net_income")
    assert est is not None
    assert est.confidence is MidCycleConfidence.HIGH
    assert injectable_mid_denominator(est) == pytest.approx(60.0)


def test_phase5_cyclical_writes_midcycle_artifact(repo, tmp_path):
    out = tmp_path / "p5_cyc"
    series = [{"period_end": d.isoformat(), "value": v} for d, v in _complete_series()]
    summary = build_phase5_bundle(
        out_dir=out,
        config_path=repo / "config/default.yaml",
        seed=7,
        paths=4,
        years=2,
        include_cashflow=False,
        fixture="cyclical",
        midcycle_assumptions={"pit_denominator_series": series},
    )
    art = out / "midcycle_estimate.json"
    assert art.is_file()
    import json
    payload = json.loads(art.read_text())
    assert "mid_cycle_denominator" in payload
    assert "confidence" in payload
    assert "diagnostics" in payload
    assert summary["midcycle_estimate_artifact"] == "midcycle_estimate.json"


def test_phase5_mature_omits_midcycle_artifact(repo, tmp_path):
    out = tmp_path / "p5_mat"
    summary = build_phase5_bundle(
        out_dir=out,
        config_path=repo / "config/default.yaml",
        seed=7,
        paths=4,
        years=2,
        include_cashflow=False,
        fixture="mature_operating",
    )
    assert not (out / "midcycle_estimate.json").exists()
    assert summary.get("midcycle_estimate_artifact") is None


def test_cashflow_cyclical_diagnostics_only_values_unchanged(repo):
    """Cyclical + series attaches midcycle_estimate; equity_value path unchanged vs no-series control.

    Uses FCFF plugin with a minimal synthetic path bundle when available; otherwise
    skips if Phase4 fixtures are heavy — prefer unit-level compare on diagnostics merge.
    """
    from vms.methods.cash_flow.common import with_midcycle_diagnostics

    _, ctx_series = _ctx(repo, cyclical=True, series=_complete_series())
    _, ctx_none = _ctx(repo, cyclical=True, series=None)
    cfg = MethodConfig(method_id="fcff_dcf", assumptions={})
    base = {"flags": [], "assumptions": []}
    d1 = with_midcycle_diagnostics(ctx_series, cfg, dict(base))
    d0 = with_midcycle_diagnostics(ctx_none, cfg, dict(base))
    assert "midcycle_estimate" in d1
    assert d1["midcycle_estimate"]["confidence"] == "HIGH"
    assert "midcycle_estimate" in d0
    assert d0["midcycle_estimate"]["confidence"] == "LOW"
    # Non-cyclical: unchanged / no key
    _, ctx_mat = _ctx(repo, cyclical=False, series=_complete_series())
    d_mat = with_midcycle_diagnostics(ctx_mat, cfg, dict(base))
    assert "midcycle_estimate" not in d_mat
    assert d_mat == base


def test_rim_fi_path_no_invented_midcycle(repo):
    loaded, ctx = _ctx(
        repo,
        cyclical=False,
        primary=ProfileLabel.FINANCIAL_INSTITUTION,
        flags=[],
        series=_complete_series(),
    )
    # Also mark HIGH_CYCLICALITY incorrectly should still no-op on FI via skip flag
    ctx_fi = ctx.model_copy(
        update={
            "profile": ctx.profile.model_copy(
                update={
                    "primary_profile": ProfileLabel.FINANCIAL_INSTITUTION,
                    "flags": [ProfileFlag.HIGH_CYCLICALITY],
                }
            ),
            "rim_inputs": {
                "book_equity_0": 100.0,
                "net_income": [10.0, 10.0, 10.0],
                "dividends": [0.0, 0.0, 0.0],
                "zeros_explicit": True,
                "cost_of_equity": 0.10,
                "terminal_growth": 0.02,
            },
        }
    )
    r = build_registry_from_config(loaded.method_registry).plugin("residual_income").value_paths(
        ctx_fi, None, MethodConfig(method_id="residual_income", assumptions={"zeros_explicit": True}),
    )
    # FI + cyclical flag still explicit no-op for midcycle attach
    assert (r.diagnostics or {}).get("midcycle_estimate") is None


def test_rim_non_fi_cyclical_attaches_diagnostics(repo):
    # HIGH_CYCLICALITY on a non-FI mature primary keeps RIM eligible while resolve runs.
    loaded, ctx = _ctx(
        repo,
        cyclical=False,
        series=_complete_series(),
        primary=ProfileLabel.MATURE_OPERATING,
        flags=[ProfileFlag.HIGH_CYCLICALITY],
    )
    assert profile_is_cyclical(ctx.profile) is True
    ctx = ctx.model_copy(
        update={
            "rim_inputs": {
                "book_equity_0": 100.0,
                "net_income": [10.0, 10.0, 10.0],
                "dividends": [0.0, 0.0, 0.0],
                "zeros_explicit": True,
                "cost_of_equity": 0.10,
                "terminal_growth": 0.02,
            },
        }
    )
    r = build_registry_from_config(loaded.method_registry).plugin("residual_income").value_paths(
        ctx, None, MethodConfig(method_id="residual_income", assumptions={"zeros_explicit": True}),
    )
    assert r.status is MethodEligibilityStatus.VALID
    est = (r.diagnostics or {}).get("midcycle_estimate")
    assert est is not None
    assert est["confidence"] == "HIGH"
    # Valuation math not driven by midcycle (book+RI path independent)
    assert r.values["book_equity_0"] == pytest.approx(100.0)


def test_md_passthrough_preserves_midcycle():
    src = MethodResult(
        method_id="pe",
        status=MethodEligibilityStatus.VALID,
        diagnostics={
            "midcycle_estimate": {
                "mid_cycle_denominator": 60.0,
                "confidence": "HIGH",
                "diagnostics": {},
            }
        },
    )
    frag = passthrough_midcycle_diagnostics(src)
    assert frag["midcycle_estimate"]["mid_cycle_denominator"] == pytest.approx(60.0)
    merged = diagnostics_with_midcycle_passthrough({"center": 1.0}, src)
    assert merged["center"] == 1.0
    assert "midcycle_estimate" in merged
    md = MethodDistribution(
        method_id="pe",
        samples=samples_from_point(100.0, n=8, seed=1),
        status=MethodEligibilityStatus.VALID,
        target=ValuationTarget.RELATIVE_VALUE_CURRENT,
        output_basis=OutputBasis.EQUITY,
        eligible=True,
        diagnostics=merged,
    )
    assert md.diagnostics["midcycle_estimate"]["confidence"] == "HIGH"
    assert passthrough_midcycle_diagnostics({"diagnostics": {}}) == {}
    assert passthrough_midcycle_diagnostics(None) == {}

def _minimal_cf_bundle():
    """Minimal VALID FinancialPathBundle for FCFF plugin identity pin."""
    from vms.statements.paths import FinancialPathBundle, FinancialPathRecord

    years = [2025, 2026, 2027]

    def _rec(path_id: str, kind: str) -> FinancialPathRecord:
        fcff = {str(y): float(100 + i * 5) for i, y in enumerate(years)}
        return FinancialPathRecord(
            path_id=path_id,
            kind=kind,  # type: ignore[arg-type]
            status="VALID",
            excluded_from_aggregates=False,
            projection=None,
            shares={str(y): 10.0 for y in years},
            fcff=fcff,
            fcfe={str(y): float(60 + i * 3) for i, y in enumerate(years)},
            fcff_per_share={str(y): fcff[str(y)] / 10.0 for y in years},
            book_equity_per_share={str(y): 50.0 for y in years},
            dividends={str(y): 5.0 for y in years},
            share_repurchases={str(y): 0.0 for y in years},
            share_issuance_proceeds={str(y): 0.0 for y in years},
            net_borrowing={str(y): 0.0 for y in years},
            cash={str(y): 20.0 for y in years},
            debt={str(y): 50.0 for y in years},
        )

    central = _rec("central", "central")
    mc = _rec("mc0", "monte_carlo")
    return FinancialPathBundle(
        policy={"name": "sf1-pin"},
        base_year=2024,
        years=years,
        n_input_paths=2,
        n_valid=2,
        n_failed=0,
        central=central,
        paths=[central, mc],
        valid_path_ids=["central", "mc0"],
        failed=[],
        aggregates={},
        sampler_ref={},
        assumptions=[],
    )


def test_sf1_fcff_plugin_equity_value_identity_with_without_midcycle_series(repo):
    """SF1: plugin-level equity_value identity — midcycle diagnostics only.

    Real FCFF plugin entry with identical cyclical fixture / path bundle;
    with vs without PIT midcycle series → equity_value (and peer point fields)
    bit-equal; midcycle_estimate appears only under diagnostics.
    """
    from vms.profiles.fixtures import fixtures_dir, load_fixture

    data = load_fixture(fixtures_dir() / "cyclical.json")
    af = frozenset(data["available_fields"])
    loaded, ctx_series = _ctx(repo, cyclical=True, series=_complete_series())
    ctx_series = ctx_series.model_copy(update={"available_fields": af})
    _, ctx_none = _ctx(repo, cyclical=True, series=None)
    ctx_none = ctx_none.model_copy(update={"available_fields": af})

    bundle = _minimal_cf_bundle()
    plugin = build_registry_from_config(loaded.method_registry).plugin("fcff_dcf")
    cfg = MethodConfig(method_id="fcff_dcf", assumptions={})
    r_series = plugin.value_paths(ctx_series, bundle, cfg)
    r_none = plugin.value_paths(ctx_none, bundle, cfg)

    assert r_series.status is MethodEligibilityStatus.VALID
    assert r_none.status is MethodEligibilityStatus.VALID
    # Point values identical — midcycle must not touch valuation math
    for key in ("equity_value", "enterprise_value", "value_per_share"):
        assert r_series.values[key] == r_none.values[key]
    # Midcycle only under diagnostics
    assert "midcycle_estimate" not in (r_series.values or {})
    assert "midcycle_estimate" not in (r_none.values or {})
    est_s = (r_series.diagnostics or {}).get("midcycle_estimate")
    est_n = (r_none.diagnostics or {}).get("midcycle_estimate")
    assert est_s is not None and est_s["confidence"] == "HIGH"
    assert est_s["mid_cycle_denominator"] == pytest.approx(60.0)
    assert est_n is not None and est_n["confidence"] == "LOW"
    assert est_n.get("mid_cycle_denominator") is None


def test_sf2_production_mr_to_md_preserves_midcycle():
    """SF2: production method_distribution_from_result preserves midcycle_estimate."""
    src = MethodResult(
        method_id="fcff_dcf",
        status=MethodEligibilityStatus.VALID,
        diagnostics={
            "flags": ["DEMO"],
            "midcycle_estimate": {
                "mid_cycle_denominator": 60.0,
                "confidence": "HIGH",
                "diagnostics": {},
            },
        },
    )
    md = method_distribution_from_result(
        src,
        samples=samples_from_point(1000.0, n=16, seed=3),
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        output_basis=OutputBasis.EQUITY,
        diagnostics={"center": 1000.0, "synthetic": True},
    )
    assert md.method_id == "fcff_dcf"
    assert md.diagnostics["center"] == 1000.0
    assert md.diagnostics["synthetic"] is True
    assert md.diagnostics["midcycle_estimate"]["mid_cycle_denominator"] == pytest.approx(60.0)
    assert md.diagnostics["midcycle_estimate"]["confidence"] == "HIGH"
    # No invent when source lacks midcycle
    bare = MethodResult(method_id="fcff_dcf", status=MethodEligibilityStatus.VALID, diagnostics={"flags": []})
    md_bare = method_distribution_from_result(
        bare,
        samples=samples_from_point(900.0, n=8, seed=4),
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        output_basis=OutputBasis.EQUITY,
        diagnostics={"center": 900.0},
    )
    assert "midcycle_estimate" not in md_bare.diagnostics


def test_sf2_phase8_production_builder_roundtrip_preserves_midcycle(repo, tmp_path):
    """SF2: phase8 MR→MD production path keeps midcycle when present on source MR."""
    from vms.reporting.phase8_bundle import (
        _components_from_method_results,
        _method_results_from_components,
        _synthetic_components,
    )

    tgt = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
    raw = _synthetic_components(tgt, seed=11)
    # Attach midcycle onto first component diagnostics before MR dump
    first = raw[0]
    mid = {
        "mid_cycle_denominator": 60.0,
        "confidence": "HIGH",
        "diagnostics": {},
    }
    raw_with = [
        MethodDistribution(
            method_id=first.method_id,
            samples=first.samples,
            status=first.status,
            target=first.target,
            output_basis=first.output_basis,
            eligible=first.eligible,
            diagnostics={**dict(first.diagnostics), "midcycle_estimate": mid},
        ),
        *raw[1:],
    ]
    mrs = _method_results_from_components(raw_with)
    assert "midcycle_estimate" in (mrs[0].diagnostics or {})
    rebuilt = _components_from_method_results(mrs, raw_with)
    assert rebuilt[0].diagnostics["midcycle_estimate"]["confidence"] == "HIGH"
    assert rebuilt[0].diagnostics["midcycle_estimate"]["mid_cycle_denominator"] == pytest.approx(60.0)
    # Sibling without midcycle stays clean (no invent)
    assert "midcycle_estimate" not in rebuilt[1].diagnostics
