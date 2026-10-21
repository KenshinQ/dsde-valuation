#!/usr/bin/env python3
"""Offline VMS-0.2 Phase 0 demo for the synthetic mature-operating fixture."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running without install when PYTHONPATH=src
ROOT = Path(__file__).resolve().parents[2]
src = ROOT / "src"
if str(src) not in sys.path and not any(p.endswith("site-packages") and "dsde" in p for p in sys.path):
    # Prefer installed package; only fall back for ad-hoc runs.
    pass

from vms.cli.main import main


def parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--paths", type=int, default=100)
    p.add_argument("--as-of", default="2025-06-30")
    p.add_argument("--target", default="FUNDAMENTAL_VALUE_CURRENT")
    p.add_argument("--config", default=str(ROOT / "config" / "default.yaml"))
    return p.parse_args()


if __name__ == "__main__":
    a = parse()
    raise SystemExit(main([
        "phase0", "--out", a.out, "--seed", str(a.seed), "--paths", str(a.paths),
        "--as-of", a.as_of, "--target", a.target, "--config", a.config,
    ]))
