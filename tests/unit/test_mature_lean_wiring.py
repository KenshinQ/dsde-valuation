"""Always-on wiring tests for MATURE lean materialize kinds (no duckdb required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vms.evaluation.universe import load_universe, materialize_universe

REPO = Path(__file__).resolve().parents[2]


def test_load_mature_lean_universe():
    uni = load_universe(REPO / "config" / "universe.mature_lean.yaml")
    assert uni.universe_id == "mature_lean_wf_v1"
    assert uni.data_label == "SYNTHETIC"
    assert uni.mature_synthetic is not None
    assert uni.mature_real is None
    assert uni.fi_real is None


def test_load_mature_lean_real_scaffold():
    uni = load_universe(REPO / "config" / "universe.mature_lean_real.yaml")
    assert uni.mature_real is not None
    assert "SYNTHETIC" not in uni.data_label.upper()
    assert uni.mature_synthetic is None


def test_materialize_mature_synthetic(tmp_path):
    uni = load_universe(REPO / "config" / "universe.mature_lean.yaml")
    panel = materialize_universe(uni, work_dir=tmp_path, prefer_local=True)
    assert len(panel) == 2
    assert (tmp_path / "mature_synthetic_materialize.json").is_file()


def test_materialize_mature_real_data_gap(tmp_path):
    uni = load_universe(REPO / "config" / "universe.mature_lean_real.yaml")
    panel = materialize_universe(uni, work_dir=tmp_path, prefer_local=True)
    assert panel == {}
    mat = (tmp_path / "mature_real_materialize.json").read_text()
    assert "DATA_GAP_NO_DATA_DIR" in mat
    assert '"rest_calls": 0' in mat


def test_mutual_exclusion_kinds(tmp_path):
    from vms.evaluation.universe import UniverseConfig, UniverseInstrument

    bad = UniverseConfig(
        universe_id="x",
        data_label="SYNTHETIC",
        instruments=[UniverseInstrument(instrument_id="A")],
        mature_synthetic={"seed": 1},
        synthetic={"seed": 1},
    )
    with pytest.raises(ValueError, match="multiple materialize kinds"):
        materialize_universe(bad, work_dir=tmp_path)


def test_mature_real_rejects_synthetic_label(tmp_path):
    from vms.evaluation.universe import UniverseConfig, UniverseInstrument

    bad = UniverseConfig(
        universe_id="x",
        data_label="SYNTHETIC_OOPS",
        instruments=[UniverseInstrument(instrument_id="A")],
        mature_real={"scaffold": True},
    )
    with pytest.raises(ValueError, match="must not contain SYNTHETIC"):
        materialize_universe(bad, work_dir=tmp_path)
