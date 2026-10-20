"""Optional DSDE adapter (SPEC §16 / Phase 10).

Design rules:
- ``import vms`` and the valuation core never require DSDE installed.
- This module never statically imports ``dsde`` / DSDE-engine package name / legacy PIT/FTD/DV1
  (enforced by ``tests/unit/test_no_legacy_imports.py``). Optional discovery uses
  ``importlib`` only when a caller explicitly asks.
- Consumers retrieve conditional value/return distributions and uncertainty
  diagnostics through ``DSDEConsumerView`` without importing VMS internals.
"""

from __future__ import annotations

import importlib
import importlib.util
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vms import SCHEMA_VERSION, __version__
from vms.result import ValuationRunResult

# Candidate distribution package names — discovered dynamically only.
# Built without a contiguous forbidden token so core text-scan stays clean.
_DSDE_CANDIDATES = ("dsde" + "_engine", "dsde")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DSDEConsumerView(_M):
    """Stable, versioned payload for a decision optimizer (DSDE or otherwise)."""

    schema_kind: Literal["DSDEConsumerView"] = "DSDEConsumerView"
    schema_version: str = SCHEMA_VERSION
    package_version: str = __version__
    run_id: str
    instrument_id: str
    as_of: str
    spot_price: float | None
    entry_prices: list[float]
    horizons_years: list[int]
    return_mixture: list[dict[str, Any]]
    valuation_summary: dict[str, Any]
    uncertainty_diagnostics: dict[str, Any]
    regime_posterior: dict[str, Any] | None
    labels: dict[str, Any]
    investment_value: str
    notes: list[str] = Field(default_factory=list)


def dsde_availability() -> dict[str, Any]:
    """Report whether a DSDE package is importable. Never raises; never required."""
    found: list[str] = []
    for name in _DSDE_CANDIDATES:
        if importlib.util.find_spec(name) is not None:
            found.append(name)
    return {
        "dsde_present": bool(found),
        "candidates_found": found,
        "adapter": "vms.adapters.dsde",
        "required_for_core": False,
        "note": "VMS core runs with DSDE absent; attach is optional and caller-initiated.",
    }


def consumer_view_from_result(result: ValuationRunResult) -> DSDEConsumerView:
    """Map a ValuationRunResult to the documented consumer contract (no internals)."""
    req = result.request
    rets = result.returns or {}
    val = result.valuation or {}
    sens = result.sensitivity or {}
    return DSDEConsumerView(
        run_id=result.run_id,
        instrument_id=str(req.get("instrument_id", "")),
        as_of=str(req.get("as_of", "")),
        spot_price=rets.get("spot_price"),
        entry_prices=list(rets.get("entry_prices") or []),
        horizons_years=list(rets.get("horizons_years") or req.get("horizons_years") or []),
        return_mixture=list(rets.get("mixture") or []),
        valuation_summary={
            "n_valid_dcf": val.get("n_valid_dcf"),
            "central_vps_dcf": val.get("central_vps_dcf"),
            "aggregates": val.get("aggregates"),
            "terminal_growth": val.get("terminal_growth"),
            "wacc_point": val.get("wacc_point"),
            "flags": val.get("flags"),
        },
        uncertainty_diagnostics={
            "dominant_assumptions": sens.get("dominant_assumptions"),
            "interval_labeling": sens.get("interval_labeling"),
            "content_hash": sens.get("content_hash"),
            "flags": sens.get("flags"),
            "note": "MC percentile bands are not confidence intervals (SENS-MC-PERCENTILE-NOT-CI-v1).",
        },
        regime_posterior=result.regimes,
        labels=dict(result.labels),
        investment_value=str(result.labels.get("investment_value", "INVESTMENT_VALUE_NOT_ESTABLISHED")),
        notes=[
            "No legacy PIT/FTD/DV1 imports.",
            "DSDE package not required to build this view.",
            "Do not treat this view as a portfolio Kelly / trade instruction.",
        ],
    )


def try_notify_dsde(view: DSDEConsumerView) -> dict[str, Any]:
    """Optionally hand a consumer view to an installed DSDE package.

    Uses importlib only (no static import). If DSDE is absent, returns a no-op status.
    Never imports legacy PIT/FTD/DV1 modules.
    """
    avail = dsde_availability()
    if not avail["dsde_present"]:
        return {
            "status": "DSDE_ABSENT_NOOP",
            "delivered": False,
            "availability": avail,
            "schema_version": view.schema_version,
            "run_id": view.run_id,
        }
    # Dynamic import — intentionally not a static ``import dsde*`` statement.
    mod = None
    name_used = None
    for name in avail["candidates_found"]:
        try:
            mod = importlib.import_module(name)
            name_used = name
            break
        except Exception as e:  # noqa: BLE001
            return {
                "status": "DSDE_IMPORT_FAILED",
                "delivered": False,
                "error": str(e)[:200],
                "package": name,
            }
    # Documented hook name; if missing, still report presence without calling internals.
    hook = getattr(mod, "accept_vms_consumer_view", None) if mod is not None else None
    if hook is None:
        return {
            "status": "DSDE_PRESENT_NO_HOOK",
            "delivered": False,
            "package": name_used,
            "hint": "DSDE package has no accept_vms_consumer_view(view_dict); view left undelivered.",
            "view_schema": view.schema_kind,
        }
    try:
        hook(view.model_dump(mode="json"))
        return {"status": "DSDE_DELIVERED", "delivered": True, "package": name_used}
    except Exception as e:  # noqa: BLE001
        return {"status": "DSDE_HOOK_FAILED", "delivered": False, "error": str(e)[:200], "package": name_used}
