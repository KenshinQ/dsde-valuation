"""Config validation (Phase 0 acceptance: invalid config fails with actionable errors)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vms.schemas.config import ConfigError, load_config, load_driver_profile


def _write_cfg(tmp_path: Path, repo: Path, mutate=None, profile_mutate=None) -> Path:
    cfg = yaml.safe_load((repo / "config/default.yaml").read_text())
    prof = yaml.safe_load((repo / "config/driver_profiles/operating_company.yaml").read_text())
    if mutate:
        mutate(cfg)
    if profile_mutate:
        profile_mutate(prof)
    (tmp_path / "driver_profiles").mkdir()
    (tmp_path / "driver_profiles/operating_company.yaml").write_text(yaml.safe_dump(prof))
    p = tmp_path / "default.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def test_shipped_configs_valid(repo):
    lc = load_config(repo / "config/default.yaml")
    assert lc.config.base_currency == "CNY"
    assert lc.profile.profile_id == "operating_company" and lc.profile.supported
    assert lc.profile.bounds_status == "placeholder"


@pytest.mark.parametrize("mutate,needles", [
    (lambda c: c.update(base_currency="USD"), ["base_currency", "CNY"]),
    (lambda c: c.update(mode="live"), ["mode", "production"]),
    (lambda c: c.update(timezone="Mars/Olympus"), ["timezone", "IANA"]),
    (lambda c: c.update(horizons_years=[0, 3]), ["horizons_years", "positive"]),
    (lambda c: c["monte_carlo"].update(default_paths=0), ["monte_carlo.default_paths", "greater than 0"]),
    (lambda c: c["monte_carlo"].update(max_invalid_path_fraction=1.5), ["max_invalid_path_fraction"]),
    (lambda c: c["entry_price_grid"].update(relative_to_spot=[1.0, -0.5]), ["relative_to_spot", "> 0"]),
    (lambda c: c["terminal_value"].update(min_wacc_minus_g=0), ["min_wacc_minus_g"]),
    (lambda c: c["returns"].update(loss_thresholds=[0.2]), ["loss_thresholds", "-0.2"]),
    (lambda c: c["returns"].update(cvar_levels=[95]), ["cvar_levels", "0.95"]),
    (lambda c: c.pop("monte_carlo"), ["monte_carlo", "Field required"]),
    (lambda c: c["quality"].update(balance_sheet_rel_tol=0), ["quality.balance_sheet_rel_tol"]),
    (lambda c: c["quality"].update(unit_jump_ratio=1), ["quality.unit_jump_ratio", "greater than 1"]),
    (lambda c: c.pop("quality"), ["quality", "Field required"]),
    (lambda c: c.update(unknown_key=1), ["unknown_key", "Extra inputs"]),
])
def test_invalid_config_actionable(tmp_path, repo, mutate, needles):
    p = _write_cfg(tmp_path, repo, mutate=mutate)
    with pytest.raises(ConfigError) as ei:
        load_config(p)
    msg = str(ei.value)
    assert str(p) in msg  # names the file
    for n in needles:
        assert n in msg, msg


@pytest.mark.parametrize("pmut,needle", [
    (lambda p: p["drivers"].append(dict(p["drivers"][0])), "duplicate driver names"),
    (lambda p: p["drivers"][0].update(lower=1, upper=0), "must be < upper"),
    (lambda p: p["drivers"][1].update(upper=1.5), "logit' requires bounds within [0, 1]"),
    (lambda p: p["drivers"][0].update(lower=-1.0), "log1p' requires lower > -1"),
    (lambda p: p["drivers"][0].update(family="magic"), "family"),
    (lambda p: p.update(drivers=[]), "at least 1"),
    (lambda p: p.update(bounds_status="guess"), "bounds_status"),
])
def test_invalid_profile_actionable(tmp_path, repo, pmut, needle):
    p = _write_cfg(tmp_path, repo, profile_mutate=pmut)
    with pytest.raises(ConfigError) as ei:
        load_config(p)
    assert needle in str(ei.value) and "operating_company.yaml" in str(ei.value)


def test_missing_file_and_bad_yaml(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [1, 2\n")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(bad)
    lst = tmp_path / "list.yaml"
    lst.write_text("- 1\n")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_driver_profile(lst)


def test_missing_profile_file(tmp_path, repo):
    p = _write_cfg(tmp_path, repo, mutate=lambda c: c.update(driver_profile="missing.yaml"))
    with pytest.raises(ConfigError, match="missing.yaml"):
        load_config(p)
