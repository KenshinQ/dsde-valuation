"""Run a command inside an already-created user+net namespace with a block self-check.

Helper for E-01 offline end-to-end smoke tests, not a pytest module.
Launch with `unshare -r --net` (or equivalent). A dummy HTTP(S) proxy
is never treated as proof that the network is unavailable.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

IP_BIN = "/usr/bin/ip"
CONNECT_TARGETS = (("1.1.1.1", 443), ("8.8.8.8", 53))
ALLOWED_CONNECT_ERRNOS = {errno.ENETUNREACH, errno.ENETDOWN}


def _sysfs_interfaces() -> list[str]:
    """Host sysfs may be stale inside a new netns if sysfs was not remounted.

    Do not treat this list as authoritative for isolation.
    """
    root = Path("/sys/class/net")
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir())


def _proc_net_interfaces() -> list[str]:
    path = Path("/proc/net/dev")
    if not path.is_file():
        return []
    names: list[str] = []
    for line in path.read_text().splitlines()[2:]:
        if ":" not in line:
            continue
        names.append(line.split(":", 1)[0].strip())
    return names


def _ip_link_interfaces() -> list[str]:
    ip = Path(IP_BIN)
    if not ip.is_file():
        return []
    r = subprocess.run(
        [str(ip), "-o", "link"], capture_output=True, text=True, check=False
    )
    names: list[str] = []
    for line in (r.stdout or "").splitlines():
        # "1: lo: <LOOPBACK,UP,LOWER_UP> ..."
        parts = line.split(":", 2)
        if len(parts) >= 2:
            name = parts[1].strip().split("@", 1)[0].strip()
            if name:
                names.append(name)
    return names


def _interfaces() -> list[str]:
    """Interfaces visible in this network namespace (proc/ip, not host sysfs)."""
    return sorted(set(_proc_net_interfaces()) | set(_ip_link_interfaces()))


def _default_route_present() -> bool:
    route = Path("/proc/net/route")
    if not route.is_file():
        return False
    lines = route.read_text().splitlines()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "00000000":
            return True
    return False


def _ip_route_text() -> str:
    ip = Path(IP_BIN)
    if not ip.is_file():
        return ""
    r = subprocess.run([str(ip), "route"], capture_output=True, text=True, check=False)
    return (r.stdout or "") + (r.stderr or "")


def bring_up_loopback() -> None:
    ip = Path(IP_BIN)
    if not ip.is_file():
        raise RuntimeError(f"{IP_BIN} is required to bring loopback up inside the netns")
    subprocess.check_call([str(ip), "link", "set", "lo", "up"])


def _connect_attempt(host: str, port: int) -> dict:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    try:
        s.connect((host, port))
    except OSError as exc:
        return {
            "target": f"{host}:{port}",
            "result": "blocked",
            "error_type": type(exc).__name__,
            "errno": exc.errno,
            "message": str(exc),
        }
    except Exception as exc:  # noqa: BLE001 — record unexpected failures honestly
        return {
            "target": f"{host}:{port}",
            "result": "unexpected",
            "error_type": type(exc).__name__,
            "errno": None,
            "message": str(exc),
        }
    finally:
        s.close()
    return {"target": f"{host}:{port}", "result": "connected", "errno": None, "message": ""}


def _proxy_keys(env: dict[str, str]) -> list[str]:
    names = []
    for key in env:
        lower = key.lower()
        if lower in {"http_proxy", "https_proxy", "all_proxy", "ftp_proxy", "no_proxy"} or lower.endswith("_proxy"):
            names.append(key)
    return sorted(names)


def _credential_like_keys(env: dict[str, str]) -> list[str]:
    needles = ("key", "token", "secret", "password", "passwd", "credential", "api_key")
    out = []
    for key in env:
        lower = key.lower()
        if any(n in lower for n in needles):
            out.append(key)
    return sorted(out)


def assert_network_unavailable() -> dict:
    interfaces = _interfaces()
    non_lo = [n for n in interfaces if n != "lo"]
    attempts = [_connect_attempt(host, port) for host, port in CONNECT_TARGETS]
    report = {
        "isolation_mechanism": "unshare -r --net (user + network namespace)",
        "proxy_used": False,
        "env_proxy_keys_present": _proxy_keys(dict(os.environ)),
        "credential_like_keys_present": _credential_like_keys(dict(os.environ)),
        "uid_in_ns": os.getuid(),
        "euid_in_ns": os.geteuid(),
        "interfaces": interfaces,
        "non_loopback_interfaces": non_lo,
        "sysfs_interfaces_may_be_host_view": _sysfs_interfaces(),
        "default_route_present": _default_route_present(),
        "ip_route": _ip_route_text().strip(),
        "connect_attempts": attempts,
    }
    failures: list[str] = []
    if report["env_proxy_keys_present"]:
        failures.append(f"proxy keys present in env: {report['env_proxy_keys_present']}")
    if report["credential_like_keys_present"]:
        failures.append(
            f"credential-like keys present in env: {report['credential_like_keys_present']}"
        )
    if non_lo:
        failures.append(f"unexpected non-loopback interfaces: {non_lo}")
    if report["default_route_present"]:
        failures.append("default route present in /proc/net/route")
    if report["ip_route"]:
        failures.append(f"ip route is not empty: {report['ip_route']!r}")
    for attempt in attempts:
        if attempt["result"] == "connected":
            failures.append(f"outbound connect succeeded: {attempt['target']}")
        elif attempt["result"] != "blocked":
            failures.append(f"unexpected connect outcome for {attempt['target']}: {attempt}")
        elif attempt["errno"] not in ALLOWED_CONNECT_ERRNOS:
            failures.append(
                f"{attempt['target']} blocked with errno {attempt['errno']}, "
                "not ENETUNREACH/ENETDOWN (a route may still exist)"
            )
    report["network_unavailable"] = not failures
    report["failures"] = failures
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolation-report", required=True)
    parser.add_argument("--cwd", default=None)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    bring_up_loopback()
    report = assert_network_unavailable()
    report_path = Path(args.isolation_report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not report["network_unavailable"]:
        sys.stderr.write("A-02 isolation self-check failed:\n")
        for item in report["failures"]:
            sys.stderr.write(f"  - {item}\n")
        return 20

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        return 0
    completed = subprocess.run(command, cwd=args.cwd or None, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
