"""pr13-sf1: pin prior_only_fi warning copy for four ingest paths (readability refactor)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vms import SCHEMA_VERSION
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.prior_only_fi_bundle import (
    _ensemble_report_warning,
    _simulation_metadata_warning,
    build_prior_only_fi_bundle,
)
from vms.schemas.contracts import ClaimStatus

INV = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value

# Frozen pre-refactor warning copy vs master @ 5e71897 (MIN=12; capital-E Equal-weight).
# Do not regenerate from helpers.
_PINNED = {
    "calibrate_rim": {
        "flags": {
            "is_calibrate_rim": True,
            "is_live": False,
            "has_live_samples": False,
            "primary_assumption": "ENSEMBLE-PRIOR-ONLY-FI-CALIBRATE-RIM-MD-v1",
        },
        "ensemble": (
            "calibrate-rim forecast → PRIOR_ONLY research mixture "
            "(ENSEMBLE-PRIOR-ONLY-FI-CALIBRATE-RIM-MD-v1). "
            "Equal-weight / exploratory baseline — NOT ENSEMBLE_CALIBRATED. "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
            "Track B requires hist_n>=12 and a PER_SHARE "
            "exit center (never raw pb_center_used P/B multiple)."
        ),
        "simulation": (
            "calibrate-rim forecast PRIOR_ONLY ingest "
            "(ENSEMBLE-PRIOR-ONLY-FI-CALIBRATE-RIM-MD-v1). Research path only. "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
            "Does not lift industry.unsupported "
            "(see ENSEMBLE-PRIOR-ONLY-FI-CALIBRATE-RIM-MD-v1). "
            "Track B hist_n < 12 or missing PER_SHARE "
            "exit center → SKIP, not in weights."
        ),
    },
    "live_samples": {
        "flags": {
            "is_calibrate_rim": False,
            "is_live": True,
            "has_live_samples": True,
            "primary_assumption": "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1",
        },
        "ensemble": (
            "R10 live value-rim path samples → PRIOR_ONLY research mixture "
            "(ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1). "
            "Equal-weight / exploratory baseline — NOT ENSEMBLE_CALIBRATED. "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
            "Track B requires hist_n>=12 and a PER_SHARE "
            "exit center (never raw pb_center_used P/B multiple)."
        ),
        "simulation": (
            "R10 live value-rim path samples PRIOR_ONLY ingest "
            "(ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1). Research path only. "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
            "Does not lift industry.unsupported "
            "(see ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1). "
            "Track B hist_n < 12 or missing PER_SHARE "
            "exit center → SKIP, not in weights."
        ),
    },
    "live": {
        "flags": {
            "is_calibrate_rim": False,
            "is_live": True,
            "has_live_samples": False,
            "primary_assumption": "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1",
        },
        "ensemble": (
            "R9 live value-rim → PRIOR_ONLY research mixture "
            "(ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1). "
            "Equal-weight / exploratory baseline — NOT ENSEMBLE_CALIBRATED. "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
            "Track B requires hist_n>=12 and a PER_SHARE "
            "exit center (never raw pb_center_used P/B multiple)."
        ),
        "simulation": (
            "R9 live value-rim PRIOR_ONLY ingest "
            "(ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1). Research path only. "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
            "Does not lift industry.unsupported "
            "(see ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1). "
            "Track B hist_n < 12 or missing PER_SHARE "
            "exit center → SKIP, not in weights."
        ),
    },
    "demo_r8": {
        "flags": {
            "is_calibrate_rim": False,
            "is_live": False,
            "has_live_samples": False,
            "primary_assumption": "ENSEMBLE-PRIOR-ONLY-FI-v1",
        },
        "ensemble": (
            "R8 FI PRIOR_ONLY research mixture (SPEC §13.3). "
            "Equal-weight / exploratory baseline — NOT ENSEMBLE_CALIBRATED. "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
            "Track B requires hist_n>=12 and a PER_SHARE "
            "exit center (never raw pb_center_used P/B multiple)."
        ),
        "simulation": (
            "R8 deposit-taking FI PRIOR_ONLY wiring. Research path only. "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
            "Does not lift industry.unsupported "
            "(see ENSEMBLE-PRIOR-ONLY-FI-v1). "
            "Track B hist_n < 12 or missing PER_SHARE "
            "exit center → SKIP, not in weights."
        ),
    },
}


@pytest.mark.parametrize("label", list(_PINNED), ids=list(_PINNED))
def test_warning_helpers_pin_four_path_full_strings(label: str) -> None:
    """AC2: helper output equals frozen pre-refactor copy on all four paths."""
    pinned = _PINNED[label]
    flags = pinned["flags"]
    ens = _ensemble_report_warning(**flags)
    sim = _simulation_metadata_warning(**flags)
    assert ens == pinned["ensemble"]
    assert sim == pinned["simulation"]
    assert INV in ens and INV in sim
    assert MIN_HIST_PB_POINTS == 12
    assert SCHEMA_VERSION == "vms-0.2.phase12"


def test_r8_demo_bundle_emits_pinned_demo_warnings(tmp_path: Path) -> None:
    """Bundle wiring uses helpers: R8 demo path matches pinned full strings."""
    build_prior_only_fi_bundle(
        tmp_path / "r8",
        scenario="track_a_pb",
        seed=7,
        n_draws=100,
    )
    ens_body = json.loads((tmp_path / "r8" / "ensemble_report.json").read_text())
    sim_body = json.loads((tmp_path / "r8" / "simulation_metadata.json").read_text())
    pinned = _PINNED["demo_r8"]
    assert ens_body["warning"] == pinned["ensemble"]
    assert sim_body["warning"] == pinned["simulation"]
    assert ens_body["investment_value"] == INV
    assert sim_body["investment_value"] == INV
    assert ens_body["calibrated_claim"] is False
    assert ens_body["schema_version"] == "vms-0.2.phase12"
