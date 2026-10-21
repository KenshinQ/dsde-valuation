#!/usr/bin/env python3
"""Offline Phase 5 relative-multiples demo wrapper."""
from __future__ import annotations

import argparse
import sys

from vms.cli.main import main


def main_argv() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--out", required=True)
    a.add_argument("--seed", type=int, default=42)
    a.add_argument("--paths", type=int, default=10)
    a.add_argument("--years", type=int, default=2)
    a.add_argument("--multiples-only", action="store_true", default=True)
    ns, _ = a.parse_known_args()
    argv = [
        "phase5", "--out", ns.out, "--seed", str(ns.seed), "--paths", str(ns.paths),
        "--years", str(ns.years),
    ]
    if ns.multiples_only:
        argv.append("--multiples-only")
    return main(argv)


if __name__ == "__main__":
    sys.exit(main_argv())
