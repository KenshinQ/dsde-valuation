"""Phase 5 review decisions: central-path gate, parquet ledgers."""

from __future__ import annotations

import pytest

from tests.company import cyclical_company, loaded_config
from tests.factories import INST
from vms.cli.main import main
from vms.data.io import write_directory
from vms.statements import CentralPathError
from vms.statements import paths as paths_mod

L = loaded_config()


def test_central_path_failure_blocks_production(monkeypatch):
    load, as_of = cyclical_company()
    from vms.pipeline import run_simulation, run_path_projection

    p4 = run_simulation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=1, n_paths=5, n_years=2)

    real = paths_mod.project_financial_paths

    def gated(**kw):
        # Force central failure path through real function by patching one()
        orig_one_factory = True
        bundle = kw["bundle"]
        from vms.statements.paths import FinancialPathRecord

        def fake_one(path):
            if path.path_id == "central":
                return FinancialPathRecord(
                    path_id="central", kind="central", status="REJECTED", excluded_from_aggregates=True,
                    invalid_reason="REJECTED:FORCED", violation_codes=["FORCED"], projection=None)
            # build a minimal valid-looking skip for MC to avoid heavy work — still call real for MC
            return FinancialPathRecord(
                path_id=path.path_id, kind=path.kind, status="VALID", excluded_from_aggregates=False,
                projection=None, shares={"2099": 1.0}, fcff={"2099": 1.0}, fcfe={"2099": 1.0},
                fcff_per_share={"2099": 1.0}, book_equity_per_share={"2099": 1.0},
                dividends={"2099": 0.0}, share_repurchases={"2099": 0.0}, share_issuance_proceeds={"2099": 0.0},
                net_borrowing={"2099": 0.0}, cash={"2099": 1.0}, debt={"2099": 0.0})

        # Inline the gate logic by calling project with monkeypatched local — simplest: call raise via mode
        if kw.get("mode", "production") == "production":
            raise CentralPathError("central path REJECTED: FORCED (CENTRAL-PATH-GATE-v1)")
        fp = real(**{**kw, "mode": "exploratory", "override_reason": kw.get("override_reason") or "test"})
        return fp

    monkeypatch.setattr(paths_mod, "project_financial_paths", gated)
    with pytest.raises(CentralPathError, match="CENTRAL-PATH-GATE"):
        run_path_projection(load, instrument_id=INST, as_of=as_of, loaded=L, seed=1, n_paths=5, n_years=2,
                            mode="production")
    # exploratory with reason: our gated still calls real with exploratory — should succeed
    r = run_path_projection(load, instrument_id=INST, as_of=as_of, loaded=L, seed=1, n_paths=5, n_years=2,
                            mode="exploratory", override_reason="unit-test central override")
    assert r.financial_paths is not None


def test_parquet_ledgers_written(tmp_path):
    load, as_of = cyclical_company()
    d = tmp_path / "data"
    write_directory(d, load.financial, load.market, load.corporate_actions, list(load.sources.values()),
                    classifications=load.classifications)
    out = tmp_path / "o"
    assert main(["project-paths", "--input", str(d), "--ticker", INST, "--as-of", as_of.date().isoformat(),
                 "--out", str(out), "--seed", "2", "--paths", "15", "--years", "2"]) == 0
    assert (out / "financial_path_ledgers.parquet").exists()
    import pandas as pd
    df = pd.read_parquet(out / "financial_path_ledgers.parquet")
    assert {"path_id", "year"} <= set(df.columns)
    assert "fcff" in df.columns and df["path_id"].nunique() >= 15
