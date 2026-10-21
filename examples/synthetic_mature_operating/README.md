# SYNTHETIC mature operating company (VMS-0.2)

**SYNTHETIC DATA: no real company, no investment meaning.**

## Phase 0 — contracts baseline

```bash
vms phase0 --out /tmp/vms_phase0 --seed 42
# or:
python examples/synthetic_mature_operating/run_phase0.py --out /tmp/vms_phase0 --seed 42
```

Emits contracts-only result bundle (`schema_version=vms-0.2.phase4`); methods all `NOT_RUN`.

## Phase 3 — driver / regime / path bundle

```bash
vms phase3 --out /tmp/vms_phase3 --seed 42 --paths 80 --years 4
# or:
python examples/synthetic_mature_operating/run_phase3.py --out /tmp/vms_phase3 --seed 42
```

Emits:

- `simulation_bundle.json` — correlated driver/regime paths (`sampler_version` persisted)
- `financial_path_bundle.json` — statement projections + capital allocation (invariants enforced)
- `state_posterior.json` — fundamental regimes + market-pricing **schema** stub (`UNAVAILABLE`)
- `simulation_metadata.json` — `PHASE3_PATH_BUNDLE_NOT_A_VALUATION`, `INVESTMENT_VALUE_NOT_ESTABLISHED`

Does **not** run FCFF/FCFE/DDM/multiples method engines, ensemble, or exit-price models.

Expected qualitative behavior:

- profile resolves to `operating_company` / SUPPORTED
- valid paths reconcile accounting invariants
- fixed seed ⇒ identical `run_id` / path aggregates
- market-pricing vocabulary (COMPRESSED/NORMAL/EXPANDED/DISLOCATION) is distinct from fundamental regimes

This example must not assert fictitious investment performance.

## Phase 4 — cash-flow methods (FCFF / FCFE / DDM)

```bash
vms phase4 --out /tmp/vms_phase4 --seed 42 --paths 40 --years 4
# or:
python examples/synthetic_mature_operating/run_phase4.py --out /tmp/vms_phase4 --seed 42
```

Emits router + `method_results.json` (`schema_version=vms-0.2.phase4`). Label:
`INVESTMENT_VALUE_NOT_ESTABLISHED`. No ensemble / exit-price / multiples.
