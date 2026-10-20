"""`vms project` exit codes and artifacts (Phase 2)."""

from __future__ import annotations

import json

import pytest

from tests.company import company
from tests.factories import INST as CINST
from vms.cli.main import main
from vms.data import synthetic
from vms.data.io import write_directory
from vms.statements.projection import LABEL

INST = synthetic.SYNTHETIC_INSTRUMENT


def _syn(tmp_path, cls=None):
    d = tmp_path / "data"
    write_directory(d, *synthetic.generate(42), synthetic.source_descriptors(),
                    classifications=synthetic.classifications() if cls is None else cls)
    return d


def _crafted(tmp_path, **kw):
    load, as_of = company(**kw)
    d = tmp_path / "data"
    write_directory(d, load.financial, load.market, load.corporate_actions, list(load.sources.values()),
                    classifications=load.classifications)
    return d, as_of.date().isoformat()


def _project(d, out, as_of="2025-06-30", ticker=INST, *extra):
    return main(["project", "--input", str(d), "--ticker", ticker, "--as-of", as_of, "--out", str(out), *extra])


def test_project_ok_artifacts(tmp_path, capsys):
    out = tmp_path / "o"
    assert _project(_syn(tmp_path), out, "2025-06-30", INST, "--policy", "fixed_payout", "--years", "3") == 0
    s = json.loads(capsys.readouterr().out)
    assert s["projection_status"] == "VALID" and s["label"] == LABEL and s["policy"] == "fixed_payout"
    assert s["years"] == [2025, 2026, 2027] and s["profile"] == "SUPPORTED"
    proj = json.loads((out / "statement_projection.json").read_text())
    drv = json.loads((out / "driver_diagnostics.json").read_text())
    snap = json.loads((out / "pit_snapshot.json").read_text())
    for a in (proj, drv, snap):
        assert a["run_id"] == s["run_id"]
    assert proj["status"] == "VALID" and "fcff@2025" in proj["items"]
    assert proj["fcff"]["kind"] == "FCFF" and proj["fcfe"]["kind"] == "FCFE"
    assert snap["pit_complete"] is True and snap["classification"]["industry"] == "机械设备"


def test_project_reproducible(tmp_path, capsys):
    d = _syn(tmp_path)
    _project(d, tmp_path / "a")
    _project(d, tmp_path / "b")
    for n in ("statement_projection.json", "driver_diagnostics.json"):
        assert (tmp_path / "a" / n).read_bytes() == (tmp_path / "b" / n).read_bytes()


def test_project_unsupported_profile_exit_4(tmp_path, capsys):
    d, as_of = _crafted(tmp_path, industry="银行")
    out = tmp_path / "o"
    assert _project(d, out, as_of, CINST) == 4
    err = capsys.readouterr().err
    assert "UNSUPPORTED_PROFILE" in err
    proj = json.loads((out / "statement_projection.json").read_text())
    assert proj["status"] == "UNSUPPORTED_PROFILE" and proj["items"] == {}


def test_project_insufficient_data_exit_5(tmp_path, capsys):
    d, as_of = _crafted(tmp_path, drop={(2024, "inventory")})
    assert _project(d, tmp_path / "o", as_of, CINST) == 5
    assert "inventory@FY2024" in capsys.readouterr().err


def test_project_blocked_exit_3(tmp_path, capsys):
    d = _syn(tmp_path)
    import pandas as pd
    p = d / "financial_observations.csv"
    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    i = df.index[(df.field_name == "capex") & (df.period_end == "2023-06-30")][0]
    df.loc[i, "value"] = "-" + df.loc[i, "value"]
    df.to_csv(p, index=False)
    out = tmp_path / "o"
    assert _project(d, out) == 3
    assert not (out / "statement_projection.json").exists()
    assert json.loads((out / "data_quality_report.json").read_text())["status"] == "BLOCKED"


@pytest.mark.parametrize("extra,needle", [(["--years", "0"], "--years"), (["--policy", "nope"], "invalid choice")])
def test_project_invalid_args(tmp_path, capsys, extra, needle):
    with pytest.raises(SystemExit) if "--policy" in extra else _nullctx():
        rc = _project(_syn(tmp_path), tmp_path / "o", "2025-06-30", INST, *extra)
        assert rc == 2
    assert needle in capsys.readouterr().err


class _nullctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
