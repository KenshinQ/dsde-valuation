"""Optional import of lab helpers under HITHINK_FUND_LIB (default /workspace/data/hithink_fund).

Never hard-crashes ``import vms`` — helpers are loaded only when the adapter runs.
Never prints or returns API keys.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from vms.providers.hithink.paths import lab_lib_path


class HiThinkUnavailable(RuntimeError):
    """Lab helpers, DuckDB, or local DB path unavailable."""


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"vms_hithink_lab_{name}", path)
    if spec is None or spec.loader is None:
        raise HiThinkUnavailable(f"cannot load lab module {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    # Register under a private name to avoid colliding with top-level lab scripts.
    sys.modules[spec.name] = mod  # type: ignore[arg-type]
    spec.loader.exec_module(mod)
    return mod


def load_lab_modules() -> dict[str, ModuleType]:
    root = lab_lib_path()
    if not root.is_dir():
        raise HiThinkUnavailable(
            f"HITHINK_FUND_LIB path missing: {root}. Set HITHINK_FUND_LIB or install lab helpers."
        )
    needed = {
        "lib_fund_store": root / "lib_fund_store.py",
        "lib_em_notices": root / "lib_em_notices.py",
        "lib_prices": root / "lib_prices.py",
    }
    missing = [str(p) for p in needed.values() if not p.is_file()]
    if missing:
        raise HiThinkUnavailable(f"lab helper files missing: {missing}")
    return {k: _load_module(k, p) for k, p in needed.items()}


def redact_secrets(obj: Any) -> Any:
    """Recursively scrub credential-like strings from structures before logging."""
    secret_keys = {"api_key", "apikey", "authorization", "token", "password", "secret",
                   "HITHINK_FINANCE_API_KEY", "hithink_finance_api_key"}
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower().replace("-", "_") in {s.lower() for s in secret_keys} or "api_key" in str(k).lower():
                out[k] = "***REDACTED***"
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(obj, list):
        return [redact_secrets(x) for x in obj]
    if isinstance(obj, str) and len(obj) > 20 and obj.startswith(("sk-", "ht_", "Bearer ")):
        return "***REDACTED***"
    return obj
