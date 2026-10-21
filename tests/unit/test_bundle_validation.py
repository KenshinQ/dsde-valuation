"""Result-bundle validation (SPEC §16.3 / Phase 12)."""

from __future__ import annotations

import json
from pathlib import Path

from vms.reporting.bundle_validation import (
    PHASE_CLI_SUBSETS,
    SECTION_16_3_MINIMUM,
    validate_result_bundle,
    write_validation_report,
)


def test_phase_cli_subsets_cover_phase0_through_12():
    for key in (
        "phase0", "phase3", "phase4", "phase5", "phase6", "phase7",
        "phase8", "phase9", "phase10", "phase11", "phase12", "phase12_mature_full",
    ):
        assert key in PHASE_CLI_SUBSETS
        assert PHASE_CLI_SUBSETS[key]


def test_section_16_3_minimum_nonempty():
    assert "method_eligibility.json" in SECTION_16_3_MINIMUM
    assert "return_distribution_summary.json" in SECTION_16_3_MINIMUM
    assert "validation_report.json" in SECTION_16_3_MINIMUM


def test_validate_missing_root(tmp_path: Path):
    res = validate_result_bundle(tmp_path / "nope", subset="phase12")
    assert res.ok is False
    assert "<root>" in res.missing


def test_validate_phase12_subset_pass(tmp_path: Path):
    root = tmp_path / "run"
    root.mkdir()
    for name in PHASE_CLI_SUBSETS["phase12"]:
        (root / name).write_text(json.dumps({
            "schema_version": "vms-0.2.phase12",
            "implemented_phase": "PHASE_12",
            "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
            "labels": {"INVESTMENT_VALUE_NOT_ESTABLISHED": True},
        }) + "\n")
    res = validate_result_bundle(root, subset="phase12")
    assert res.ok is True
    assert not res.missing
    assert res.investment_label == "INVESTMENT_VALUE_NOT_ESTABLISHED"


def test_validate_rejects_supported_true(tmp_path: Path):
    root = tmp_path / "bad"
    root.mkdir()
    for name in PHASE_CLI_SUBSETS["phase12"]:
        payload = {
            "schema_version": "vms-0.2.phase12",
            "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
        }
        if name == "simulation_metadata.json":
            payload["INVESTMENT_VALUE_SUPPORTED"] = True  # forbidden true claim
        (root / name).write_text(json.dumps(payload) + "\n")
    res = validate_result_bundle(root, subset="phase12")
    assert res.ok is False
    assert res.alpha_claim_violations


def test_write_validation_report(tmp_path: Path):
    root = tmp_path / "run"
    root.mkdir()
    for name in PHASE_CLI_SUBSETS["phase12"]:
        if name == "validation_report.json":
            continue
        (root / name).write_text(json.dumps({
            "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
            "labels": {"INVESTMENT_VALUE_NOT_ESTABLISHED": True},
        }) + "\n")
    # first write leaves validation_report missing → fail, then present after write
    payload = write_validation_report(root, subset="phase12")
    assert (root / "validation_report.json").is_file()
    assert "status" in payload
