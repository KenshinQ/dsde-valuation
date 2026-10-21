# Method registry (VMS-0.2)

Source of truth for machine config: [`config/method_registry.yaml`](../config/method_registry.yaml)
(`registry_version` stamped per phase). Plugin contract: SPEC §11.1.

## Implemented methods (Phase 4–6)

| method_id | Family | Output basis | Typical eligible profiles | Notes |
|---|---|---|---|---|
| `fcff_dcf` | Cash-flow | EV → equity → per-share | Mature, growth, cyclical, asset-heavy | **Disabled** for `FINANCIAL_INSTITUTION` by exclusion |
| `fcfe_dcf` | Cash-flow | Equity / per-share | Mature, growth, financial, cyclical | Needs coherent net borrowing |
| `ddm` | Cash-flow | Equity / per-share | Dividend-paying where payout modelable | Hard-gated if dividends not modelable |
| `pe` / `pb` / `ev_ebit` / `ev_ebitda` / `ev_sales` | Multiples | Relative → equity/EV | Operating profiles with PIT peers | Negative / near-zero denominators rejected; PIT peer filter mandatory |
| `residual_income` | Earnings | Equity | Financial institutions (book + ROE) | Clean-surplus diagnostics |
| `nav` | Asset | Asset NAV / equity | Holding / asset-heavy | Requires asset/claims schedule |
| `sotp` | Asset | SOTP equity | Holding / conglomerate | Segment inputs + holding discount explicit |

## Routing rules (summary)

1. Classify economic profile (deterministic rules; optional logged override).
2. Enumerate registry entries for the **requested valuation target**.
3. Apply **hard eligibility gates** (profile, fields, peers, quality, conceptual exclusions).
4. Attach soft suitability scores (not calibrated weights).
5. Run only eligible methods; retain disagreement.
6. Ensemble only after compatibility + calibration protocol; otherwise `PRIOR_ONLY` research mixture or none.

Anti-patterns (SPEC §22): no universal FCFF default; no averaging unlike objects; no equal-weight “calibrated” blend without evidence.

## Status vocabulary

`NOT_RUN`, `INELIGIBLE`, `UNSUPPORTED`, `FAILED`, `LOW_CONFIDENCE`, `VALID` (and coverage `INSUFFICIENT_METHOD_COVERAGE`).

## CLI

```bash
vms route --fixture examples/profile_fixtures/mature_operating.json --target FUNDAMENTAL_VALUE_CURRENT
vms phase4 ...   # cash-flow via router
vms phase5 ...   # multiples + PIT peers
vms phase6 ...   # RIM / NAV / SOTP (synthetic)
vms value-rim --input … --ticker 000001.SZ --as-of 2025-06-30  # R1 real PIT→RIM
vms compare-methods --fixture mature
```

## R1 real PIT → RIM

`vms value-rim` bridges a real A-share PIT snapshot to `residual_income` without lifting
`industry.unsupported`. Legacy `vms project` / `vms value` remain `UNSUPPORTED_PROFILE` for
configured unsupported industries. NI forecast is constant last-FY parent NI (ASSUMPTION);
missing OCI/net_issuance require `zeros_explicit` (`CLEAN_SURPLUS_ZEROS_ASSUMED`).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. See `PHASE_R1_BANK_RIM_DONE.md`.
