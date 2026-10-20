"""Regenerate docs/assumptions.md from vms.assumptions (kept in sync by tests/unit/test_docs_sync.py)."""

from pathlib import Path

from vms.assumptions import ASSUMPTIONS, SUPERSEDED

HEADER = """# Versioned assumption register (VMS-0.1)

Source of truth: `src/vms/assumptions.py` (`ASSUMPTIONS`, `SUPERSEDED`). `tests/unit/test_docs_sync.py` keeps this
table in sync; regenerate with `python scripts/gen_assumptions_doc.py`. Artifacts cite the IDs they rely on
(e.g. `statement_projection.json → assumptions`). **Changing an assumption means adding `-v2`, never silently
editing `-v1`.** Superseded IDs stay listed and can no longer be cited (`cite()` raises).

Owner decisions: scope/data items (ASOF, SCOPE-CNY, PIT-INCOMPLETE, PRICE-REVISION-DEFER, RIGHTS-ADJ-DEFER,
STALENESS, SOURCE-CONFLICT) after Phase 1 review; ANNUAL-BASE-STALENESS, INDUSTRY-UNCLASSIFIED-v2,
DIVIDEND-T-PLUS-1, ANNOUNCED-DIVIDEND-BASE, INTEREST-OPENING-DEBT-v2, REVOLVER-RATE, CASH-INTEREST-ZERO,
BS-RESIDUAL-WARN, LEASE-BRIDGE-DEBTLIKE, MINORITY-BOOK-BRIDGE, WACC-INPUTS-DEFERRED after Phase 2 review (2026-10-20).

## Notes for later phases
- **Phase 4:** sample parameters from the persisted parameter-uncertainty draws and the Dirichlet transition
  posterior; do not collapse the uncertainty types (SPEC §8.1).
- **Phase 5:** dilution from rights issues/placements enters through share-count paths (RIGHTS-ADJ-DEFER-v1).
- **Phase 6:** leases are debt-like in the bridge and FCFF must not also deduct lease principal (LEASE-BRIDGE-DEBTLIKE-v1).
  Minority interest at book (MINORITY-BOOK-BRIDGE-v1). Dividends declared on the final FY are unpaid at the horizon
  (DIVIDEND-T-PLUS-1-v1). WACC inputs need an owner decision (WACC-INPUTS-DEFERRED-v1).
- **Phase 7:** holders at as_of receive announced dividends with ex_date > as_of (ANNOUNCED-DIVIDEND-BASE-v1).
- **Phase 9:** exclude snapshots with `pit_complete == false` from unbiased evaluation metrics (PIT-INCOMPLETE-v1).

| ID | Status | Assumption |
|---|---|---|
"""


def render() -> str:
    rows = []
    for k, v in ASSUMPTIONS.items():
        assert "|" not in v, k
        status = f"superseded by `{SUPERSEDED[k]}`" if k in SUPERSEDED else "active"
        rows.append(f"| `{k}` | {status} | {v} |")
    return HEADER + "\n".join(rows) + "\n"


if __name__ == "__main__":
    Path(__file__).resolve().parents[1].joinpath("docs/assumptions.md").write_text(render(), encoding="utf-8")
