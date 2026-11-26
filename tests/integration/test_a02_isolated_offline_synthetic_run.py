"""A-02: smallest complete synthetic workflow with the network actually unavailable.

VTP A-02 Pass requires a versioned result bundle (profile, routing decision,
method results, market exit-price distribution, return distribution,
diagnostics, provenance) produced while network access is unavailable.

Setting http_proxy/https_proxy and inheriting os.environ is not isolation
(P1-E1 audit). These tests use an unprivileged user+network namespace
(`unshare -r --net`), self-check that outbound TCP fails with
ENETUNREACH/ENETDOWN on a clean environment with no proxy and no
credential-like variables, then run the production `phase12` CLI.

Fail-closed: if `unshare -r --net` cannot be created or the self-check
does not prove unavailability, the test fails (it is not skipped). A
dummy proxy is never treated as offline.

This does not close backlog item 6 (offline E2E smoke). It does not
claim ENGINEERING_ACCEPTED or investment value.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from vms import SCHEMA_VERSION
from vms.reporting.bundle_validation import validate_result_bundle
from vms.reporting.phase12_bundle import INVESTMENT_LABEL, PHASE12_STATUS

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "tests" / "integration" / "a02_isolated_netns_runner.py"
UNSHARE = Path("/usr/bin/unshare")

REQUIRED_BUNDLE_FILES = (
    "profile_report.json",
    "route_report.json",
    "method_eligibility.json",
    "method_results.json",
    "market_pricing_report.json",
    "exit_price_summary.json",
    "return_distribution_summary.json",
    "diagnostics.json",
    "simulation_metadata.json",
    "config_snapshot.json",
    "request.json",
    "validation_report.json",
    "phase12_summary.json",
)

# Minimal child environment: do not inherit os.environ (proxies, tokens, keys).
_ENV_PATH = "/usr/bin:/bin"


def _clean_env() -> dict[str, str]:
    env = {
        "PATH": _ENV_PATH,
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(REPO / "src"),
    }
    if "TZ" in os.environ:
        env["TZ"] = os.environ["TZ"]
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        env["VIRTUAL_ENV"] = venv
        env["PATH"] = str(Path(venv) / "bin") + ":" + env["PATH"]
    elif sys.prefix != sys.base_prefix:
        env["VIRTUAL_ENV"] = sys.prefix
        env["PATH"] = str(Path(sys.prefix) / "bin") + ":" + env["PATH"]
    tmp = os.environ.get("TMPDIR")
    if tmp:
        env["TMPDIR"] = tmp
    return env


def _require_unshare() -> None:
    if not UNSHARE.is_file():
        pytest.fail(
            "A-02 isolation requires /usr/bin/unshare; it is not present. "
            "Fail-closed (not skipped); a proxy is not a substitute."
        )
    probe = subprocess.run(
        [str(UNSHARE), "-r", "--net", "true"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if probe.returncode != 0:
        pytest.fail(
            "A-02 isolation requires `unshare -r --net`; it failed here "
            f"(exit {probe.returncode}): {(probe.stderr or probe.stdout).strip()!r}. "
            "Fail-closed (not skipped); a proxy is not a substitute."
        )


def _run_isolated(
    *command: str,
    isolation_report: Path,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    _require_unshare()
    if not RUNNER.is_file():
        pytest.fail(f"missing isolation runner: {RUNNER}")
    env = _clean_env()
    leaked = [
        key
        for key in env
        if key.lower().endswith("proxy")
        or any(n in key.lower() for n in ("key", "token", "secret", "password", "credential"))
    ]
    assert not leaked, f"clean env must not carry proxy or credential-like keys: {leaked}"
    return subprocess.run(
        [
            str(UNSHARE),
            "-r",
            "--net",
            sys.executable,
            str(RUNNER),
            "--isolation-report",
            str(isolation_report),
            "--cwd",
            str(REPO),
            "--",
            *command,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(REPO),
        env=env,
        check=False,
    )


def _load_report(path: Path) -> dict:
    assert path.is_file(), f"isolation self-check report was not written: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _host_connect(host: str, port: int) -> dict:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    try:
        s.connect((host, port))
        result = {"target": f"{host}:{port}", "result": "connected"}
    except OSError as exc:
        result = {
            "target": f"{host}:{port}",
            "result": "failed",
            "error_type": type(exc).__name__,
            "errno": exc.errno,
            "message": str(exc),
        }
    finally:
        s.close()
    return result


def test_isolated_netns_blocks_outbound_without_proxy(tmp_path: Path) -> None:
    report_path = tmp_path / "isolation_self_check.json"
    result = _run_isolated(isolation_report=report_path)
    report = _load_report(report_path)
    assert result.returncode == 0, (
        f"isolation self-check failed (exit {result.returncode}): "
        f"{result.stderr or result.stdout}\nreport={report}"
    )
    assert report["network_unavailable"] is True
    assert report["proxy_used"] is False
    assert report["env_proxy_keys_present"] == []
    assert report["credential_like_keys_present"] == []
    assert report["non_loopback_interfaces"] == []
    assert report["default_route_present"] is False
    assert report["ip_route"] == ""
    assert {row["target"]: row["errno"] for row in report["connect_attempts"]}


def test_a02_smallest_complete_synthetic_workflow_network_unavailable(tmp_path: Path) -> None:
    """Production phase12 mature_operating inside a proven-unavailable netns."""
    out = tmp_path / "bundle"
    report_path = tmp_path / "isolation_self_check.json"
    host_contrast = {
        "note": "Host contrast is evidence that the block is from the netns, not a dead host NIC. "
        "A-02 does not require the host itself to have connectivity.",
        "attempts": [_host_connect("1.1.1.1", 443)],
    }
    (tmp_path / "host_contrast.json").write_text(
        json.dumps(host_contrast, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = _run_isolated(
        sys.executable,
        "-m",
        "vms.cli.main",
        "phase12",
        "--out",
        str(out),
        "--pattern",
        "mature_operating",
        "--seed",
        "42",
        "--paths",
        "10",
        "--years",
        "2",
        "--spot",
        "10.0",
        isolation_report=report_path,
        timeout=180,
    )
    report = _load_report(report_path)
    assert report["network_unavailable"] is True, report
    assert report["proxy_used"] is False
    assert report["env_proxy_keys_present"] == []
    assert report["credential_like_keys_present"] == []
    assert result.returncode == 0, (
        f"phase12 failed under isolated netns (exit {result.returncode}): "
        f"{result.stderr or result.stdout}"
    )

    for name in REQUIRED_BUNDLE_FILES:
        path = out / name
        assert path.is_file(), f"required A-02 artifact missing: {name}"
        assert path.stat().st_size > 0, f"required A-02 artifact is empty: {name}"

    validation = validate_result_bundle(out, subset="phase12_mature_full")
    assert validation.ok, getattr(validation, "missing", validation)

    summary = json.loads((out / "phase12_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == PHASE12_STATUS
    assert summary["investment_value"] == INVESTMENT_LABEL
    assert summary["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summary["labels"]["INVESTMENT_VALUE_NOT_ESTABLISHED"] is True
    assert summary["labels"]["INVESTMENT_VALUE_SUPPORTED"] is False
    assert summary["schema_version"] == SCHEMA_VERSION
    assert summary["pattern"] == "mature_operating"
    assert summary["primary_profile"] == "MATURE_OPERATING"
    assert summary["method_outcome"] == "CASHFLOW_METHODS"
    assert summary["track_b_outcome"] == "EXIT_AND_RETURNS"
    assert summary["validation_ok"] is True

    profile = json.loads((out / "profile_report.json").read_text(encoding="utf-8"))
    assert profile["primary_profile"] == "MATURE_OPERATING"
    assert profile.get("profile_probabilities") or profile.get("profile_scores")

    route = json.loads((out / "route_report.json").read_text(encoding="utf-8"))
    assert route["profile_primary"] == "MATURE_OPERATING"
    assert route.get("eligibility")
    assert route.get("coverage_status")

    methods = json.loads((out / "method_results.json").read_text(encoding="utf-8"))
    assert methods.get("results"), "method results must be non-empty"

    exit_summary = json.loads((out / "exit_price_summary.json").read_text(encoding="utf-8"))
    assert exit_summary.get("bundle") or exit_summary.get("fingerprint")

    returns = json.loads((out / "return_distribution_summary.json").read_text(encoding="utf-8"))
    assert returns.get("horizons_years") or returns.get("mixture") or returns.get("path_returns_sample")

    diagnostics = json.loads((out / "diagnostics.json").read_text(encoding="utf-8"))
    assert isinstance(diagnostics, dict) and diagnostics

    metadata = json.loads((out / "simulation_metadata.json").read_text(encoding="utf-8"))
    assert metadata["schema_version"] == SCHEMA_VERSION
    assert metadata["seed"] == 42
    assert metadata.get("run_id")
    assert metadata.get("config_hash")
    assert metadata["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"

    config = json.loads((out / "config_snapshot.json").read_text(encoding="utf-8"))
    assert config.get("configuration_version")
    assert isinstance(config.get("config"), dict)

    # The workflow ran in the same namespace invocation as the block self-check.
    # stdout is the phase12 summary JSON (after the runner's self-check passed).
    printed = json.loads(result.stdout)
    assert printed["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert printed["validation_ok"] is True

