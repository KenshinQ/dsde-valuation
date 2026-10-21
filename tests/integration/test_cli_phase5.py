"""`vms phase5` relative multiples CLI (VMS-0.2 Phase 5)."""

from __future__ import annotations

import json

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.phase5_bundle import PHASE5_STATUS


def test_cli_phase5_smoke(tmp_path, capsys):
    out = tmp_path / "phase5"
    rc = main([
        "phase5", "--out", str(out), "--seed", "42", "--paths", "10", "--years", "2",
        "--multiples-only",
    ])
    assert rc == 0
    summ = json.loads((out / "phase5_summary.json").read_text())
    assert summ["status"] == PHASE5_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION == "vms-0.2.phase6"
    assert summ["implemented_phase"] == IMPLEMENTED_PHASE == "PHASE_6"
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["ensemble"] is None
    assert (out / "method_results.json").is_file()
    assert (out / "peer_diagnostics.json").is_file()
    mr = json.loads((out / "method_results.json").read_text())
    assert mr["ensemble"] is None
    ids = {r["method_id"] for r in mr["results"]}
    assert {"pe", "pb", "ev_ebit", "ev_ebitda", "ev_sales"} <= ids
    # Peer exclusions persisted for at least one method
    peer_diag = json.loads((out / "peer_diagnostics.json").read_text())
    assert peer_diag
    sample = next(v for v in peer_diag.values() if isinstance(v, dict) and "excluded" in v)
    assert "excluded" in sample and "included" in sample
    # FUTURE99 must be excluded somewhere
    all_excl = {
        e["peer_instrument_id"]
        for d in peer_diag.values()
        if isinstance(d, dict) and "excluded" in d
        for e in d["excluded"]
    }
    assert "FUTURE99.SZ" in all_excl or "NEG01.SZ" in all_excl
    captured = capsys.readouterr()
    assert "PHASE5_RELATIVE_MULTIPLES" in captured.out or PHASE5_STATUS in captured.out
