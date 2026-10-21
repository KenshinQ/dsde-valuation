#!/usr/bin/env python3
"""Offline Phase 12 example for pattern=growth_negative_fcf (synthetic; NOT investment advice)."""
from __future__ import annotations

import argparse
from pathlib import Path

from vms.reporting.phase12_bundle import build_phase12_pattern, dump_summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--paths", type=int, default=20)
    p.add_argument("--years", type=int, default=3)
    p.add_argument("--config", default=None)
    args = p.parse_args()
    summary = build_phase12_pattern(
        out_dir=args.out,
        pattern="growth_negative_fcf",
        config_path=args.config,
        seed=args.seed,
        paths=args.paths,
        years=args.years,
    )
    print(dump_summary(summary), end="")
    assert summary["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summary["labels"]["INVESTMENT_VALUE_SUPPORTED"] is False
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
