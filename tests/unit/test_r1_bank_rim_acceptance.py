"""R1 acceptance: real A-share bank → RIM bridge + legacy FCFF gate retained."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from vms.data.io import LoadResult
from vms.drivers.profiles import ProfileStatus, resolve_profile
from vms.methods import MethodConfig, build_registry_from_config
from vms.methods.protocol import ValuationContext
from vms.methods.rim.from_snapshot import features_from_snapshot, rim_inputs_from_snapshot
from vms.pit.asof import parse_as_of
from vms.pit.snapshot import build_snapshot
from vms.profiles import classify_profile
from vms.router import route_methods
from vms.schemas import (
    FinancialObservation,
    InstrumentClassification,
    MarketObservation,
    SourceDescriptor,
)
from vms.schemas.config import load_config
from vms.schemas.contracts import MethodEligibilityStatus, ProfileLabel, ValuationTarget
from vms.schemas.fields import get_field

CST = timezone(timedelta(hours=8))
INST = "000001.SZ"


def _ts(d: str, hh: int = 18) -> datetime:
    return datetime.combine(date.fromisoformat(d), time(hh), CST)


def _f(period_end: str, field: str, value, pub: str) -> FinancialObservation:
    f = get_field(field)
    return FinancialObservation(
        instrument_id=INST, period_end=date.fromisoformat(period_end), published_at=_ts(pub),
        statement_type=f.statement_type if f else "income", field_name=field, value=value,
        currency="CNY", unit_scale="unit", source_id="S", revision_id="r0", quality_status="observed",
    )


def _bank_snap():
    fins = []
    for y, te, ni, rev, div, ta in [
        (2023, 472.0e9, 46.455e9, 164.699e9, 13.773e9, 5.5e12),
        (2024, 494.842e9, 44.508e9, 146.695e9, 26.807e9, 5.7e12),
    ]:
        pe, pub = f"{y}-12-31", f"{y+1}-03-15"
        fins.extend([
            _f(pe, "total_equity", te, pub),
            _f(pe, "parent_net_income", ni, pub),
            _f(pe, "revenue", rev, pub),
            _f(pe, "dividends_paid", div, pub),
            _f(pe, "total_assets", ta, pub),
            _f(pe, "total_liabilities", ta - te, pub),
        ])
    mkts = [
        MarketObservation(
            instrument_id=INST, timestamp=_ts("2025-06-30", 15), raw_close=12.07,
            adjusted_close=None, shares_outstanding=1.9405918198e10, currency="CNY", source_id="S",
        ),
    ]
    cls = InstrumentClassification(
        instrument_id=INST, scheme="SW2021_L1", industry="银行",
        published_at=_ts("1991-04-03", 15), source_id="em_f10_industry",
    )
    load = LoadResult(
        financial=fins, market=mkts, corporate_actions=[],
        sources={"S": SourceDescriptor(source_id="S", reporting_convention="CN_CUMULATIVE_YTD",
                                       versioning="FULL_HISTORY")},
        classifications=[cls],
    )
    as_of, _ = parse_as_of("2025-06-30")
    snap, _, _ = build_snapshot(
        instrument_id=INST, as_of=as_of, financial=load.financial, market=load.market,
        corporate_actions=[], sources=load.sources, classifications=load.classifications,
    )
    return snap, load


def test_ac1_legacy_industry_unsupported_unchanged(repo):
    """Legacy industrial profile resolution still UNSUPPORTED for 银行 (reject B)."""
    loaded = load_config(repo / "config/default.yaml")
    snap, _ = _bank_snap()
    assert "银行" in loaded.config.industry.unsupported
    res = resolve_profile(snap.classification, loaded.config.industry)
    assert res.status is ProfileStatus.UNSUPPORTED_PROFILE


def test_ac2_3_4_5_6_rim_bridge_route_and_value(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap, _ = _bank_snap()
    feats = features_from_snapshot(snap)
    profile = classify_profile(feats)
    assert profile.primary_profile is ProfileLabel.FINANCIAL_INSTITUTION
    assert profile.primary_profile is not ProfileLabel.MATURE_OPERATING

    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=True, equity_basis="total")
    assert bridge.ok
    assert bridge.rim_inputs["book_equity_0"] == 494.842e9
    assert bridge.rim_inputs["zeros_explicit"] is True
    assert "CLEAN_SURPLUS_ZEROS_ASSUMED" in bridge.flags

    registry = build_registry_from_config(loaded.method_registry)
    fields = frozenset({
        "total_equity", "parent_net_income", "dividends_paid", "revenue",
        "ebit", "cash_flow_from_operations", "capex", "interest_bearing_debt", "cash",
    })
    route = route_methods(
        registry=registry, profile=profile, target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        available_fields=fields, attempt_value_paths=False, context_loaded=loaded,
        rim_inputs=bridge.rim_inputs,
    )
    by_id = {e.method_id: e for e in route.eligibility}
    assert by_id["residual_income"].eligible is True
    assert by_id["fcff_dcf"].eligible is False
    route_rel = route_methods(
        registry=registry, profile=profile, target=ValuationTarget.RELATIVE_VALUE_CURRENT,
        available_fields=fields, attempt_value_paths=False, context_loaded=loaded,
    )
    by_rel = {e.method_id: e for e in route_rel.eligibility}
    assert by_rel["ev_ebitda"].eligible is False

    plugin = registry.plugin("residual_income")
    assert plugin is not None
    ctx = ValuationContext(
        instrument_id=INST, as_of=snap.as_of.isoformat(), target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        profile=profile, available_fields=fields, loaded=loaded, rim_inputs=bridge.rim_inputs,
        subject_metrics={"total_equity": bridge.rim_inputs["book_equity_0"]},
    )
    result = plugin.value_paths(ctx, None, MethodConfig(method_id="residual_income", assumptions=dict(bridge.rim_inputs)))
    assert result.status is MethodEligibilityStatus.VALID
    assert result.values["ev_bridge_applied"] is False
    assert result.values["equity_value"]["mean"] > 0
    assert result.values.get("value_per_share") is not None
    assert "CLEAN_SURPLUS_ZEROS_ASSUMED" in (result.diagnostics.get("flags") or [])
