"""Generate the SYNTHETIC operating-company dataset (seeded, offline).

Usage:
    python examples/synthetic_operating_company/generate_data.py --seed 42 --out examples/synthetic_operating_company/data

All records are labeled source_id=SYNTHETIC. They describe no real company.
"""

from __future__ import annotations

import argparse

from vms.data import synthetic
from vms.data.io import write_directory


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", required=True)
    p.add_argument("--format", choices=["csv", "parquet"], default="csv")
    a = p.parse_args()
    fin, mkt, ca = synthetic.generate(a.seed)
    write_directory(a.out, fin, mkt, ca, synthetic.source_descriptors(), fmt=a.format,
                    classifications=synthetic.classifications())
    print(f"SYNTHETIC data written to {a.out}: {len(fin)} financial, {len(mkt)} market, "
          f"{len(ca)} corporate-action records (seed={a.seed})")


if __name__ == "__main__":
    main()
