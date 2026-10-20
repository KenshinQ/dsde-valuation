"""Regenerate docs/assumptions.md from vms.assumptions (kept in sync by tests/unit/test_docs_sync.py)."""

from pathlib import Path

from vms.assumptions import ASSUMPTIONS, SUPERSEDED

HEADER = """# Versioned assumption register (VMS-0.1)

Source of truth: `src/vms/assumptions.py` (`ASSUMPTIONS`, `SUPERSEDED`). `tests/unit/test_docs_sync.py` keeps this
table in sync; regenerate with `python scripts/gen_assumptions_doc.py`. Artifacts cite the IDs they rely on
(e.g. `statement_projection.json → assumptions`). **Changing an assumption means adding `-v2`, never silently
editing `-v1`.** Superseded IDs stay listed and can no longer be cited (`cite()` raises).

Owner decisions: scope/data after Phase 1; Phase 2 follow-ups (2026-10-20); Phase 3 review (2026-10-20):
CENTRAL-FROM-SELECTED, persistence_t selection, REGIME-CLOCK-MISMATCH, INDUSTRY-PRIORS-DEFER,
MODEL-SELECTION-WF-v2 eval gates; Phase 6 WACC-INPUTS-v1 (same day); Phase 4 follow-ups (PARAM-BOOTSTRAP-COUPLED, INVALID-PATH-FRACTION-GATE, DEP-BLOCK-BOOTSTRAP-DEFER, COVERAGE-MISCAL-NO-AUTOSWITCH) and Phase 5 PATH-STATEMENTS / FAILED-PATHS-EXCLUDED; Phase 5 review: CENTRAL-PATH-GATE, PATH-LEDGER-PARQUET, BUYBACK-PRICE-LAST-CLOSE; Phase 6 WACC-RF-CONFIG / TV-GORDON / EXIT-MULTIPLE-SEPARATE / EV-EQUITY-BRIDGE; Phase 7 DIVIDEND-NO-REINVEST / HORIZON-EQUITY-REMAINING-PV / ANNUALIZED-GEO-ENDYEAR / ENTRY-PRICE-GRID / PRICE-REGIME-INVARIANT; Phase 8 SENS-OAT-ISOLATION / SENS-MC-PERCENTILE-NOT-CI / SENS-PROCESS-VS-PARAM / SENS-DRIVER-ABLATION; Phase 9 EVAL-CHRONOLOGICAL-ONLY / EVAL-FORECAST-BEFORE-OUTCOME / EVAL-TARGETS-SEPARATE / EVAL-INVESTMENT-LABEL.

## Notes for later phases
- **Phase 5 (done):** path-wise statements consume SimulationBundle drivers (PATH-STATEMENTS-v1); failed paths excluded (FAILED-PATHS-EXCLUDED-v1). Dilution from rights: RIGHTS-ADJ-DEFER-v1.
- **Phase 6:** leases debt-like in the bridge (LEASE-BRIDGE-DEBTLIKE-v1); minority at book
  (MINORITY-BOOK-BRIDGE-v1); unpaid final-FY dividends (DIVIDEND-T-PLUS-1-v1); WACC-INPUTS-v1
  (10y CGB RF, ERP 6% default swept, beta vs CSI 300 2y weekly shrink-to-1).
- **Phase 7 (done):** entry-price returns with DIVIDEND-NO-REINVEST-v1; horizon equity via remaining FCFF PV (HORIZON-EQUITY-REMAINING-PV-v1); holders at as_of also receive announced dividends with ex_date > as_of (ANNOUNCED-DIVIDEND-BASE-v1) via the path cash/DPS construction.
- **Phase 8 (done):** OAT/joint sensitivity, process vs param, driver ablation, MC percentile ≠ CI.
- **Phase 9 (done):** chronological walk-forward evaluation; synthetic => INVESTMENT_VALUE_NOT_ESTABLISHED.
- **Phase 9 note:** exclude snapshots with `pit_complete == false` from unbiased evaluation metrics (PIT-INCOMPLETE-v1).

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
