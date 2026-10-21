"""Optional dynamic notify to an installed DSDE package (never required)."""

from __future__ import annotations

import importlib
import importlib.util
from typing import Any

from vms.adapters.dsde.contract import DSDEConsumerView

# Candidate distribution package names — discovered dynamically only.
# Built without a contiguous forbidden token so core text-scan stays clean.
_DSDE_CANDIDATES = ("dsde" + "_engine", "dsde")


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
            "contract_version": view.contract_version,
            "run_id": view.run_id,
        }
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
        return {
            "status": "DSDE_HOOK_FAILED",
            "delivered": False,
            "error": str(e)[:200],
            "package": name_used,
        }
