"""Phase 10: optional DSDE adapter — core works without DSDE; no legacy imports."""

from __future__ import annotations

import ast
import importlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from vms import SCHEMA_VERSION
from vms.adapters import dsde
from vms.adapters.dsde import (DSDEConsumerView, consumer_view_from_result, dsde_availability,
                               try_notify_dsde)
from vms.quality.report import DataQualityReport, QualityState
from vms.result import ValuationRunResult
from vms.schemas.observations import ValuationRequest

TZ = ZoneInfo("Asia/Shanghai")


def test_dsde_absent_availability():
    a = dsde_availability()
    assert a["dsde_present"] is False
    assert a["required_for_core"] is False
    assert a["adapter"] == "vms.adapters.dsde"


def test_try_notify_noop_when_absent():
    view = DSDEConsumerView(
        run_id="vms-test",
        instrument_id="SYN000001.SZ",
        as_of="2025-06-30T15:00:00+08:00",
        spot_price=10.0,
        entry_prices=[10.0],
        horizons_years=[1, 3],
        return_mixture=[],
        valuation_summary={},
        uncertainty_diagnostics={},
        regime_posterior=None,
        labels={"investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED", "ENGINEERING_PASS": True},
        investment_value="INVESTMENT_VALUE_NOT_ESTABLISHED",
    )
    st = try_notify_dsde(view)
    assert st["status"] == "DSDE_ABSENT_NOOP"
    assert st["delivered"] is False


def _stub_quality() -> DataQualityReport:
    return DataQualityReport(
        instrument_id="SYN000001.SZ",
        as_of=datetime(2025, 6, 30, 15, 0, tzinfo=TZ),
        mode="exploratory",
        status=QualityState.PASS,
        pit_complete=True,
        usable_for_production=True,
        checks=[],
        issues=[],
        severity_counts={},
        excluded_post_as_of={},
        override=None,
    )


def test_consumer_view_from_minimal_result():
    req = ValuationRequest(
        instrument_id="SYN000001.SZ",
        as_of=datetime(2025, 6, 30, 15, 0, tzinfo=TZ),
        spot_price=12.0,
        horizons_years=[1, 3],
        monte_carlo_paths=10,
        random_seed=1,
        configuration_version="test",
    )
    result = ValuationRunResult.build(
        run_id="vms-unit",
        request=req,
        quality=_stub_quality(),
        regimes=None,
        distributions=None,
        simulation=None,
        financial=None,
        valuation=None,
        returns=None,
        sensitivity=None,
        profile_id=None,
        profile_status="UNSUPPORTED_PROFILE",
        unsupported=True,
        flags=["UNIT_STUB"],
    )
    assert result.schema_version == SCHEMA_VERSION == "vms-0.2.phase4"
    assert result.labels["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    view = consumer_view_from_result(result)
    assert view.schema_kind == "DSDEConsumerView"
    assert view.investment_value == "INVESTMENT_VALUE_NOT_ESTABLISHED"


def test_adapter_module_has_no_static_dsde_import():
    src = Path(dsde.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"dsde_engine", "dsde", "pit", "ftd", "dv1"}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in forbidden:
                    found.append(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in forbidden:
                found.append(node.module)
    assert found == [], found


def test_import_vms_alone():
    importlib.invalidate_caches()
    m = importlib.import_module("vms")
    assert m.SCHEMA_VERSION == "vms-0.2.phase4"
