"""VMS-0.2 Phase 0 contract enums and registry validation (SPEC §§6, 7, 10, 11, 17.4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from vms.schemas import (
    ClaimStatus,
    MethodEligibilityStatus,
    MethodImplementationStatus,
    MethodRegistryConfig,
    MethodRegistryEntry,
    MethodStatusRecord,
    ObservationQualityStatus,
    Phase0ClaimLabels,
    ProfileFlag,
    ProfileLabel,
    ProfilesCatalogConfig,
    RouterConfig,
    ValuationRequest,
    ValuationTarget,
    format_validation_error,
)
from vms.schemas.config import ConfigError, load_config, load_method_registry, load_profiles_catalog, load_router


CST = timezone(timedelta(hours=8))


def test_valuation_targets_match_spec():
    assert {t.value for t in ValuationTarget} == {
        "FUNDAMENTAL_VALUE_CURRENT", "FUNDAMENTAL_VALUE_HORIZON", "RELATIVE_VALUE_CURRENT",
        "MARKET_EXIT_PRICE", "ASSET_NAV", "TOTAL_RETURN",
    }


def test_method_status_and_claim_enums():
    assert {s.value for s in MethodEligibilityStatus} == {
        "NOT_RUN", "INELIGIBLE", "FAILED", "LOW_CONFIDENCE", "VALID",
    }
    assert ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert ObservationQualityStatus.OBSERVED.value == "OBSERVED"


def test_profile_flags_match_spec():
    assert {f.value for f in ProfileFlag} == {
        "CURRENT_FCF_NEGATIVE", "EARNINGS_NEGATIVE_OR_UNSTABLE", "DIVIDEND_PAYING",
        "HIGH_CASH_OR_NET_CASH", "HIGH_LEVERAGE", "MAJOR_DILUTION",
        "MATERIAL_NONOPERATING_ASSETS", "HIGH_CYCLICALITY", "SHORT_PUBLIC_HISTORY",
        "MATERIAL_SEGMENT_COMPLEXITY", "LOW_DATA_QUALITY",
    }


def test_profile_catalog_covers_baseline_labels(repo):
    cat = load_profiles_catalog(repo / "config/profiles.yaml")
    assert {p.label for p in cat.profiles} == set(ProfileLabel)


def test_method_registry_loads_declared_unimplemented(repo):
    reg = load_method_registry(repo / "config/method_registry.yaml")
    assert len(reg.methods) >= 8 and {m.method_id for m in reg.enabled_methods} == {"fcff_dcf", "fcfe_dcf", "ddm"}
    assert all(m.failure_codes and m.output_basis and m.supported_targets for m in reg.methods)
    assert load_router(repo / "config/router.yaml").require_hard_gates is True


def test_shipped_default_loads_sidecars(repo):
    lc = load_config(repo / "config/default.yaml")
    assert lc.config.configuration_version.startswith("vms-default-0.2")
    assert lc.method_registry.registry_version.startswith("vms-method-registry-0.2")
    assert lc.router.default_target is ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
    assert len(lc.profiles_catalog.profiles) >= 8


def test_enabled_not_implemented_method_rejected():
    with pytest.raises(ValidationError) as ei:
        MethodRegistryEntry(
            method_id="fcff_dcf",
            version="1",
            implementation_status=MethodImplementationStatus.NOT_IMPLEMENTED,
            enabled=True,
            supported_targets=[ValuationTarget.FUNDAMENTAL_VALUE_CURRENT],
            output_basis=["EV"],
            failure_codes=["METHOD_NOT_IMPLEMENTED"],
        )
    msg = format_validation_error(ei.value)
    assert "enabled=true" in msg and "IMPLEMENTED" in msg


def test_implemented_requires_targets():
    with pytest.raises(ValidationError) as ei:
        MethodRegistryEntry(
            method_id="fcff_dcf",
            version="1",
            implementation_status=MethodImplementationStatus.IMPLEMENTED,
            enabled=True,
            supported_targets=[],
            output_basis=["EV"],
            failure_codes=["X"],
        )
    assert "supported_targets" in format_validation_error(ei.value)


def test_duplicate_method_ids_rejected():
    entry = dict(
        method_id="x", version="1", implementation_status="NOT_IMPLEMENTED", enabled=False,
        supported_targets=["FUNDAMENTAL_VALUE_CURRENT"], output_basis=["EV"],
        failure_codes=["METHOD_NOT_IMPLEMENTED"],
    )
    with pytest.raises(ValidationError) as ei:
        MethodRegistryConfig(registry_version="t", methods=[entry, entry])
    assert "duplicate method_id" in format_validation_error(ei.value)


def test_bad_router_target_actionable(tmp_path):
    p = tmp_path / "router.yaml"
    p.write_text("router_version: t\nrequire_hard_gates: true\n"
                 "allow_ensemble_without_calibration: false\n"
                 "default_target: NOT_A_TARGET\n")
    with pytest.raises(ConfigError) as ei:
        load_router(p)
    msg = str(ei.value)
    assert str(p) in msg and "default_target" in msg


def test_bad_profile_label_actionable(tmp_path):
    p = tmp_path / "profiles.yaml"
    p.write_text("catalog_version: t\nprofiles:\n  - label: NOPE\n    description: x\n")
    with pytest.raises(ConfigError) as ei:
        load_profiles_catalog(p)
    assert "label" in str(ei.value)


def test_valuation_request_rejects_bad_target(req_kwargs):
    with pytest.raises(ValidationError) as ei:
        ValuationRequest(**{**req_kwargs, "target": "intrinsic_guess"})
    msg = format_validation_error(ei.value)
    assert "target" in msg and "FUNDAMENTAL_VALUE_CURRENT" in msg


def test_valuation_request_default_target(req_kwargs):
    r = ValuationRequest(**req_kwargs)
    assert r.target is ValuationTarget.FUNDAMENTAL_VALUE_CURRENT


def test_method_status_record_and_phase0_labels():
    rec = MethodStatusRecord(method_id="fcff_dcf", status=MethodEligibilityStatus.NOT_RUN,
                             reason="phase0", target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT)
    assert rec.status is MethodEligibilityStatus.NOT_RUN
    labels = Phase0ClaimLabels(ENGINEERING_PASS=True)
    assert labels.investment_value == "INVESTMENT_VALUE_NOT_ESTABLISHED"


def test_missing_registry_file_names_path(tmp_path, repo):
    import shutil
    import yaml
    cfg_dir = tmp_path / "cfg"
    shutil.copytree(repo / "config", cfg_dir)
    (cfg_dir / "method_registry.yaml").unlink()
    with pytest.raises(ConfigError, match="method_registry.yaml"):
        load_config(cfg_dir / "default.yaml")
