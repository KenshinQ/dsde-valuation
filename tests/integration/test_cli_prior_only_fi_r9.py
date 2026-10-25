"""`vms prior-only-fi --from-value-rim` CLI (R9)."""

from __future__ import annotations

import json
from pathlib import Path

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.fi_method_distribution_adapter import (
    ARTIFACT_METHOD_RESULT,
    ARTIFACT_RIM_PB_ROE,
    ARTIFACT_RIM_TRACK_B,
    LIVE_DATA_LABEL,
)
from vms.reporting.prior_only_fi_bundle import PRIOR_ONLY_FI_STATUS


def _write(dir_path: Path, name: str, payload: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / name).write_text(json.dumps(payload), encoding="utf-8")


def _fixture(
    root: Path,
    *,
    hist_n: int = 5,
    pb_multiple: float = 0.85,
    exit_vps: float | None = None,
    include_track_a: bool = True,
) -> Path:
    if include_track_a:
        _write(
            root,
            ARTIFACT_METHOD_RESULT,
            {
                "method_id": "residual_income",
                "status": "VALID",
                "values": {"value_per_share": {"mean": 12.0, "p50": 12.0}},
                "diagnostics": {},
            },
        )
    _write(
        root,
        ARTIFACT_RIM_PB_ROE,
        {"ok": True, "status": "VALID", "relative_vps": 10.5},
    )
    tb: dict = {
        "ok": hist_n >= MIN_HIST_PB_POINTS and exit_vps is not None,
        "status": (
            "VALID"
            if hist_n >= MIN_HIST_PB_POINTS and exit_vps is not None
            else "INELIGIBLE"
        ),
        "hist_pb": {"n": hist_n, "median": pb_multiple},
        "pb_center_used": pb_multiple,
    }
    if exit_vps is not None:
        tb["exit_prices"] = {
            "metric_id": "pb",
            "summaries": {
                "1": {
                    "n_valid": 16,
                    "mean": float(exit_vps),
                    "p50": float(exit_vps),
                    "p05": float(exit_vps) * 0.9,
                    "p95": float(exit_vps) * 1.1,
                }
            },
        }
    _write(root, ARTIFACT_RIM_TRACK_B, tb)
    return root


def test_cli_from_value_rim_smoke(tmp_path, capsys):
    vr = _fixture(tmp_path / "vr", hist_n=5, pb_multiple=0.85)
    out = tmp_path / "pofi_live"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--from-value-rim", str(vr),
        "--seed", "42",
        "--n-draws", "300",
    ])
    assert rc == 0
    summ = json.loads((out / "prior_only_fi_summary.json").read_text())
    assert summ["status"] == PRIOR_ONLY_FI_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION == "vms-0.2.phase12"
    assert summ["implemented_phase"] == IMPLEMENTED_PHASE == "PHASE_12"
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["calibrated_claim"] is False
    assert summ["ENSEMBLE_CALIBRATED"] is False
    assert summ["production_mixture"] is False
    assert summ["research_mixture"] is True
    assert summ["research_mode"] == "PRIOR_ONLY"
    assert summ["track_b_in_weights"] is False
    assert summ["data_label"] == LIVE_DATA_LABEL
    assert summ["scenario"] == "live_value_rim"
    assert summ["assumption"] == "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1"
    assert (out / "ensemble_report.json").is_file()
    assert (out / "method_results" / "residual_income.json").is_file()
    rim = json.loads((out / "method_results" / "residual_income.json").read_text())
    assert rim["diagnostics"]["synthetic"] is False
    assert rim["diagnostics"]["sample_generation"] == "samples_from_point"
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["calibrated_claim"] is False
    assert payload["data_label"] == LIVE_DATA_LABEL


def test_cli_from_value_rim_rejects_with_scenario(tmp_path, capsys):
    vr = _fixture(tmp_path / "vr2", hist_n=5)
    out = tmp_path / "conflict"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--from-value-rim", str(vr),
        "--scenario", "track_b_skip",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "mutually exclusive" in err


def test_cli_demo_without_from_value_rim_unchanged(tmp_path, capsys):
    out = tmp_path / "demo"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--seed", "42",
        "--scenario", "track_b_skip",
        "--n-draws", "300",
    ])
    assert rc == 0
    summ = json.loads((out / "prior_only_fi_summary.json").read_text())
    assert summ["data_label"].startswith("SYNTHETIC_FI_PRIOR_ONLY")
    assert summ["track_b_in_weights"] is False
    assert summ["research_mixture"] is True
    assert summ["assumption"] == "ENSEMBLE-PRIOR-ONLY-FI-v1"
    rim = json.loads((out / "method_results" / "residual_income.json").read_text())
    assert rim["diagnostics"]["synthetic"] is True


def test_cli_from_value_rim_missing_dir(tmp_path, capsys):
    out = tmp_path / "missing_out"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--from-value-rim", str(tmp_path / "no_such_vr"),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "does not exist" in err


def test_cli_from_value_rim_malformed_json(tmp_path, capsys):
    vr = tmp_path / "bad_vr"
    vr.mkdir()
    (vr / ARTIFACT_METHOD_RESULT).write_text("{not-json", encoding="utf-8")
    out = tmp_path / "bad_out"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--from-value-rim", str(vr),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "failed to read" in err


def test_cli_from_value_rim_track_a_missing(tmp_path, capsys):
    vr = _fixture(tmp_path / "no_ta", hist_n=5, include_track_a=False)
    out = tmp_path / "no_ta_out"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--from-value-rim", str(vr),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "Track A" in err
