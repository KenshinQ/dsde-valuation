"""PASS-claim plumbing (EVAL-CALIBRATION-PASS-CLAIM-PROTOCOL-v1) — SPEC slice C AC4."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vms.evaluation.labels import assign_labels
from vms.evaluation.pass_claim import (
    MIN_UNBIASED_FOR_PASS,
    PROTOCOL_ID,
    PassClaimArtifactError,
    gate_calibration_ok,
    resolve_pass_claim,
    validate_pass_claim_artifact,
)
from vms.schemas.contracts import ClaimStatus


def _valid_artifact(**overrides):
    body = {
        "protocol_id": PROTOCOL_ID,
        "universe_data_label": "REAL_A_SHARE_FI_DEPOSIT_LEAN",
        "n_unbiased": 0,
        "pit_incomplete_excluded": True,
    }
    body.update(overrides)
    return body


def test_ac4_no_artifact_insufficient():
    """No --pass-claim-artifact → never authorized; assign_labels stays INSUFFICIENT."""
    d = resolve_pass_claim(None, run_data_label="REAL_A_SHARE", run_n_unbiased=99)
    assert d.authorized is False
    assert d.reason == "NO_ARTIFACT"
    assert gate_calibration_ok(True, pass_claim=d) is None
    lab = assign_labels(
        engineering_ok=True,
        data_quality_ok=True,
        calibration_ok=True,  # candidate
        data_label="REAL_A_SHARE",
        n_unbiased_scored=99,
        pass_claim_authorized=d.authorized,
    )
    assert lab["CALIBRATION_CLAIM"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
    assert lab["CALIBRATION_PASS"] is not True
    assert lab["pass_claim_authorized"] is False


def test_ac4_bad_artifact_fail_closed(tmp_path: Path):
    """Illegal / incomplete / synthetic artifact → raise (fail-closed)."""
    # incomplete
    bad = tmp_path / "incomplete.json"
    bad.write_text(json.dumps({"protocol_id": PROTOCOL_ID}), encoding="utf-8")
    with pytest.raises(PassClaimArtifactError, match="incomplete"):
        resolve_pass_claim(bad, run_data_label="REAL_A_SHARE", run_n_unbiased=10)

    # wrong protocol
    wrong = tmp_path / "wrong.json"
    wrong.write_text(
        json.dumps(_valid_artifact(protocol_id="NOT-A-PROTOCOL")),
        encoding="utf-8",
    )
    with pytest.raises(PassClaimArtifactError, match="protocol_id"):
        resolve_pass_claim(wrong, run_data_label="REAL_A_SHARE", run_n_unbiased=10)

    # synthetic label in artifact
    syn = tmp_path / "syn.json"
    syn.write_text(
        json.dumps(_valid_artifact(universe_data_label="SYNTHETIC_LEAN")),
        encoding="utf-8",
    )
    with pytest.raises(PassClaimArtifactError, match="synthetic"):
        resolve_pass_claim(syn, run_data_label="REAL_A_SHARE", run_n_unbiased=10)

    # pit_incomplete_excluded not true
    pit = tmp_path / "pit.json"
    pit.write_text(
        json.dumps(_valid_artifact(pit_incomplete_excluded=False)),
        encoding="utf-8",
    )
    with pytest.raises(PassClaimArtifactError, match="pit_incomplete_excluded"):
        validate_pass_claim_artifact(json.loads(pit.read_text()))

    # synthetic run label even with otherwise-valid artifact
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(_valid_artifact(n_unbiased=10)), encoding="utf-8")
    with pytest.raises(PassClaimArtifactError, match="synthetic run"):
        resolve_pass_claim(ok, run_data_label="SYNTHETIC", run_n_unbiased=10)


def test_ac4_valid_artifact_but_n_zero_still_insufficient(tmp_path: Path):
    """Valid artifact structure + n_unbiased=0 → still INSUFFICIENT (plumbing ≠ evidence)."""
    art = tmp_path / "valid_n0.json"
    art.write_text(
        json.dumps(_valid_artifact(n_unbiased=0, universe_data_label="REAL_A_SHARE")),
        encoding="utf-8",
    )
    d = resolve_pass_claim(art, run_data_label="REAL_A_SHARE", run_n_unbiased=0)
    assert d.authorized is False
    assert d.reason == "INSUFFICIENT_N_UNBIASED"
    assert MIN_UNBIASED_FOR_PASS == 5
    assert gate_calibration_ok(True, pass_claim=d) is None
    lab = assign_labels(
        engineering_ok=True,
        data_quality_ok=True,
        calibration_ok=True,
        data_label="REAL_A_SHARE",
        n_unbiased_scored=0,
        pass_claim_authorized=d.authorized,
    )
    assert lab["CALIBRATION_CLAIM"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
    assert lab["CALIBRATION_PASS"] is not True


def test_authorized_when_valid_and_n_sufficient(tmp_path: Path):
    """Plumbing can authorize when artifact + run n meet MIN (still no real evidence here)."""
    art = tmp_path / "valid_n5.json"
    art.write_text(
        json.dumps(_valid_artifact(n_unbiased=5, universe_data_label="REAL_A_SHARE")),
        encoding="utf-8",
    )
    d = resolve_pass_claim(art, run_data_label="REAL_A_SHARE", run_n_unbiased=5)
    assert d.authorized is True
    assert d.reason == "AUTHORIZED"
    assert gate_calibration_ok(True, pass_claim=d) is True
    lab = assign_labels(
        engineering_ok=True,
        data_quality_ok=True,
        calibration_ok=True,
        data_label="REAL_A_SHARE",
        n_unbiased_scored=5,
        pass_claim_authorized=d.authorized,
    )
    assert lab["CALIBRATION_PASS"] is True
    assert lab["CALIBRATION_CLAIM"] == ClaimStatus.CALIBRATION_PASS.value
