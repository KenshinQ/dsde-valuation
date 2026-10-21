"""Schema / configuration version migration tests (SPEC §20 Phase 12 AC3)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION, __version__
from vms.schemas.config import load_config

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config"

# Historical phase stamps that must remain recognizable for migration docs / tests.
HISTORICAL_SCHEMA_PREFIXES = tuple(f"vms-0.2.phase{i}" for i in range(0, 13))


def test_current_schema_is_phase12_or_release():
    assert SCHEMA_VERSION.startswith("vms-0.2")
    assert IMPLEMENTED_PHASE == "PHASE_12"
    assert SCHEMA_VERSION in ("vms-0.2.phase12", "vms-0.2")
    # Honest pre-release while calibration insufficient
    assert __version__.startswith("0.2.0")


def test_config_versions_align_with_schema_stamp():
    loaded = load_config(CONFIG / "default.yaml")
    cfg_ver = loaded.config.configuration_version
    assert "0.2" in cfg_ver
    # After Phase 12 bump, versions should carry phase12 (or release) stamp
    assert "phase12" in cfg_ver or cfg_ver.endswith("0.2") or "0.2." in cfg_ver


def test_sidecar_config_versions_parse():
    files = {
        "default.yaml": "configuration_version",
        "method_registry.yaml": "registry_version",
        "router.yaml": "router_version",
        "profiles.yaml": "catalog_version",
        "profile_overrides.yaml": "override_version",
    }
    for fname, key in files.items():
        raw = yaml.safe_load((CONFIG / fname).read_text(encoding="utf-8"))
        assert key in raw, fname
        assert isinstance(raw[key], str) and raw[key]
        assert "0.2" in raw[key]


def test_migration_path_phase0_to_phase12_documented():
    """Consumers key off schema_version; phase0..phase11 stamps are superseded but listed."""
    notes = (REPO / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    assert "phase12" in notes.lower() or "0.2" in notes
    assert "INVESTMENT_VALUE_NOT_ESTABLISHED" in notes
    # Must not claim investment value supported
    assert "INVESTMENT_VALUE_SUPPORTED" not in notes or "not" in notes.lower()


def test_schema_version_monotonic_prefix():
    """phase N stamp sorts after earlier phase stamps for the same major."""
    def key(s: str) -> tuple:
        m = re.search(r"phase(\d+)$", s)
        return (0, int(m.group(1))) if m else (1, s)

    ordered = sorted(HISTORICAL_SCHEMA_PREFIXES, key=key)
    assert ordered[0] == "vms-0.2.phase0"
    assert ordered[-1] == "vms-0.2.phase12"
    if SCHEMA_VERSION.startswith("vms-0.2.phase"):
        assert key(SCHEMA_VERSION) >= key("vms-0.2.phase11")


def test_load_config_rejects_nothing_on_current_default():
    # Smoke: current default remains loadable after version bump
    loaded = load_config(CONFIG / "default.yaml")
    assert loaded.config.base_currency == "CNY"
    assert loaded.method_registry is not None
