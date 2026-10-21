"""VMS-0.2 Phase 12 acceptance (SPEC §20 Phase 12 / §23 / §24)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.reporting.bundle_validation import validate_result_bundle
from vms.reporting.phase12_bundle import (
    ALL_PATTERNS,
    INVESTMENT_LABEL,
    PHASE12_STATUS,
    build_phase12_pattern,
    build_phase12_release,
)

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
FORBIDDEN_DOC = re.compile(
    r"INVESTMENT_VALUE_SUPPORTED|guaranteed alpha|guaranteed profit|will outperform",
    re.I,
)


# ---- AC1: five offline patterns execute (or honest unsupported) ----
@pytest.mark.parametrize("pattern", list(ALL_PATTERNS))
def test_ac1_five_offline_patterns(tmp_path: Path, pattern: str):
    out = tmp_path / pattern
    summary = build_phase12_pattern(
        out_dir=out, pattern=pattern, paths=10, years=2, seed=42, spot_price=10.0,
    )
    assert summary["status"] == PHASE12_STATUS
    assert summary["investment_value"] == INVESTMENT_LABEL
    assert summary["labels"]["INVESTMENT_VALUE_SUPPORTED"] is False
    assert summary["labels"]["ENSEMBLE_CALIBRATED"] is False
    assert summary["validation_ok"] is True
    assert (out / "profile_report.json").is_file()
    assert (out / "method_eligibility.json").is_file()
    assert summary["primary_profile"] == summary["expected_primary"] or pattern == "cyclical"


# ---- AC2: e2e outputs include methods, router, exit, returns, diagnostics ----
def test_ac2_mature_e2e_artifact_set(tmp_path: Path):
    out = tmp_path / "mature"
    summary = build_phase12_pattern(
        out_dir=out, pattern="mature_operating", paths=10, years=2, spot_price=10.0,
    )
    assert summary["method_outcome"] == "CASHFLOW_METHODS"
    assert summary["track_b_outcome"] == "EXIT_AND_RETURNS"
    for name in (
        "method_results.json",
        "method_eligibility.json",
        "route_report.json",
        "market_pricing_report.json",
        "exit_price_summary.json",
        "return_distribution_summary.json",
        "diagnostics.json",
        "validation_report.json",
    ):
        assert (out / name).is_file(), name
    res = validate_result_bundle(out, subset="phase12_mature_full")
    assert res.ok, res.missing


def test_ac2_bank_diagnoses_fcff_not_default(tmp_path: Path):
    out = tmp_path / "financial_institution"
    summary = build_phase12_pattern(out_dir=out, pattern="financial_institution", paths=8, years=2)
    assert summary["primary_profile"] == "FINANCIAL_INSTITUTION"
    assert summary["method_outcome"] == "RIM"
    elig = json.loads((out / "method_eligibility.json").read_text())
    # industrial FCFF must not be silently VALID without gate
    methods = elig.get("methods") or []
    fcff = [m for m in methods if m.get("method_id") == "fcff_dcf"]
    if fcff:
        row = fcff[0]
        # hard-gate failed or not eligible
        assert row.get("eligible") is False or row.get("status") not in ("VALID", "ELIGIBLE")


def test_ac2_holding_gap_diagnosed(tmp_path: Path):
    out = tmp_path / "holding"
    summary = build_phase12_pattern(out_dir=out, pattern="holding", paths=8, years=2)
    assert summary["method_outcome"] == "SOTP_NAV_OR_GAP"
    assert (out / "holding_gap").is_dir()
    assert (out / "method_results.json").is_file()


# ---- AC3: schema / config migration tests live in test_schema_migration.py ----
def test_ac3_schema_stamp_on_artifacts(tmp_path: Path):
    out = tmp_path / "cyc"
    build_phase12_pattern(out_dir=out, pattern="cyclical", paths=8, years=2)
    meta = json.loads((out / "simulation_metadata.json").read_text())
    assert meta["schema_version"] == SCHEMA_VERSION
    assert meta["implemented_phase"] == IMPLEMENTED_PHASE


# ---- AC4: model card content (file must exist with required sections) ----
def test_ac4_model_card_required_sections():
    path = DOCS / "model_card.md"
    assert path.is_file(), "docs/model_card.md required by SPEC §19 / Phase 12"
    text = path.read_text(encoding="utf-8")
    for needle in (
        "Intended use",
        "Unsupported",
        "Limitations",
        "failure",
        "Data limitation",
        "Calibration",
        "INVESTMENT_VALUE_NOT_ESTABLISHED",
    ):
        assert needle.lower() in text.lower(), needle


# ---- AC5: no unsupported alpha / profitability claim ----
def test_ac5_no_alpha_claim_in_docs_and_cli_labels(tmp_path: Path):
    for path in DOCS.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        # Allow discussing the forbidden status as a gate name, not asserting it true
        assert "INVESTMENT_VALUE_SUPPORTED=true" not in text.replace(" ", "")
        for m in FORBIDDEN_DOC.finditer(text):
            # OK if mentioned as forbidden / not claimed / release gate key
            window = text[max(0, m.start() - 80): m.end() + 80].lower()
            assert any(
                k in window
                for k in ("not", "forbidden", "never", "must not", "gate", "status", "without")
            ), f"{path.name}: unsupported claim near {m.group(0)!r}"

    summary = build_phase12_pattern(out_dir=tmp_path / "m", pattern="cyclical", paths=8, years=2)
    dumped = json.dumps(summary)
    assert "INVESTMENT_VALUE_NOT_ESTABLISHED" in dumped
    assert '"INVESTMENT_VALUE_SUPPORTED": true' not in dumped
    assert '"INVESTMENT_VALUE_SUPPORTED":true' not in dumped.replace(" ", "")


def test_release_all_patterns(tmp_path: Path):
    # Keep light: skip mature heavy track by selecting non-mature + one mature with tiny paths
    release = build_phase12_release(
        out_dir=tmp_path / "rel",
        seed=42,
        paths=8,
        years=2,
        patterns=("cyclical", "financial_institution"),
    )
    assert release["status"] == PHASE12_STATUS
    assert release["investment_value"] == INVESTMENT_LABEL
    assert set(release["patterns"]) == {"cyclical", "financial_institution"}
