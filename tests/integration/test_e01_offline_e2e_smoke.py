"""E-01 offline end-to-end smoke: official production CLI path under a proven-unavailable netns.

Backlog item 6 / VTP Gap #9 (offline E2E + replay). Distinct from:

- A-02: smallest complete synthetic workflow (`phase12 --pattern mature_operating`)
- VTP-criteria E-01: routing truth table (backlog item 9 / 10×12×4)

Fail-closed: if `unshare -r --net` cannot be created or the self-check does
not prove unavailability, the test fails (it is not skipped). A dummy
proxy is never treated as offline.

Does not claim ENGINEERING_ACCEPTED or investment value. Does not close
I-M04, Suite G, or Suite J.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.e01_offline_e2e_smoke import assert_replay_acceptable, official_asserts

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "tests" / "integration" / "e01_isolated_netns_runner.py"
DRIVER = REPO / "tests" / "integration" / "e01_offline_e2e_smoke.py"
UNSHARE = Path("/usr/bin/unshare")


def _clean_env() -> dict[str, str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(REPO),
        "E01_REPO": str(REPO),
    }
    src = REPO / "src"
    env["PYTHONPATH"] = str(src) + os.pathsep + env["PYTHONPATH"]
    if "TZ" in os.environ:
        env["TZ"] = os.environ["TZ"]
    if sys.prefix != sys.base_prefix:
        env["VIRTUAL_ENV"] = sys.prefix
        env["PATH"] = str(Path(sys.prefix) / "bin") + ":" + env["PATH"]
    elif os.environ.get("VIRTUAL_ENV"):
        env["VIRTUAL_ENV"] = os.environ["VIRTUAL_ENV"]
        env["PATH"] = str(Path(env["VIRTUAL_ENV"]) / "bin") + ":" + env["PATH"]
    if os.environ.get("TMPDIR"):
        env["TMPDIR"] = os.environ["TMPDIR"]
    return env


def _require_unshare() -> None:
    if not UNSHARE.is_file():
        pytest.fail(
            "E-01 isolation requires /usr/bin/unshare; it is not present. "
            "Fail-closed (not skipped); a proxy is not a substitute."
        )
    probe = subprocess.run(
        [str(UNSHARE), "-r", "--net", "true"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if probe.returncode != 0:
        pytest.fail(
            "E-01 isolation requires `unshare -r --net`; it failed here "
            f"(exit {probe.returncode}): {(probe.stderr or probe.stdout).strip()!r}. "
            "Fail-closed (not skipped); a proxy is not a substitute."
        )


def _run_isolated(out: Path, isolation_report: Path, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    _require_unshare()
    if not RUNNER.is_file() or not DRIVER.is_file():
        pytest.fail(f"missing isolation runner or driver: {RUNNER} {DRIVER}")
    env = _clean_env()
    env["E01_OUT"] = str(out)
    leaked = [
        key for key in env
        if key.lower().endswith("proxy")
        or any(n in key.lower() for n in ("key", "token", "secret", "password", "credential"))
    ]
    assert not leaked, f"clean env must not carry proxy or credential-like keys: {leaked}"
    return subprocess.run(
        [
            str(UNSHARE), "-r", "--net",
            sys.executable, str(RUNNER),
            "--isolation-report", str(isolation_report),
            "--cwd", str(REPO),
            "--", sys.executable, str(DRIVER),
        ],
        capture_output=True, text=True, timeout=timeout, cwd=str(REPO), env=env, check=False,
    )


def test_e01_official_production_path_smoke_and_replay_under_isolated_netns(tmp_path: Path) -> None:
    out = tmp_path / "e01"
    report_path = tmp_path / "isolation_self_check.json"
    result = _run_isolated(out, report_path, timeout=180)
    assert report_path.is_file(), f"isolation report missing: {result.stderr or result.stdout}"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["network_unavailable"] is True, report
    assert report["proxy_used"] is False
    assert report["env_proxy_keys_present"] == []
    assert report["credential_like_keys_present"] == []
    assert report["non_loopback_interfaces"] == []
    assert report["default_route_present"] is False
    assert result.returncode == 0, (
        f"E-01 smoke/replay failed under isolated netns (exit {result.returncode}): "
        f"{result.stderr or result.stdout}"
    )

    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    run1 = out / "run1"
    run2 = out / "run2"
    official_asserts(run1)
    cmp = json.loads((out / "replay_comparison.json").read_text(encoding="utf-8"))
    assert_replay_acceptable(run1, run2, cmp)
    assert summary["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summary["replay_comparison"]["n_differed"]["snap"] == 0
    assert summary["replay_comparison"]["n_differed"]["ret"] == 0
    # Host contrast is evidence, not a requirement that the host is online.
    try:
        s = socket.socket(); s.settimeout(3.0)
        s.connect(("1.1.1.1", 443))
        host = "connected"
    except OSError as exc:
        host = f"failed:{type(exc).__name__}:{exc.errno}"
    finally:
        s.close()
    (tmp_path / "host_contrast.txt").write_text(host + "\n", encoding="utf-8")
