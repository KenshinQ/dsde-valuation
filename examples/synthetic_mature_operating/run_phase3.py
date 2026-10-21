#!/usr/bin/env python3
"""Offline VMS-0.2 Phase 3 path-bundle demo for the synthetic mature-operating fixture."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from vms.cli.main import main


def parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--paths", type=int, default=80)
    p.add_argument("--years", type=int, default=4)
    p.add_argument("--as-of", default="2025-06-30")
    p.add_argument("--config", default=str(ROOT / "config" / "default.yaml"))
    return p.parse_args()


if __name__ == "__main__":
    a = parse()
    raise SystemExit(main([
        "phase3", "--out", a.out, "--seed", str(a.seed), "--paths", str(a.paths),
        "--years", str(a.years), "--as-of", a.as_of, "--config", a.config,
    ]))
