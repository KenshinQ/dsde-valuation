# Architecture (VMS-0.2 Phase 12)

Adaptive Multi-Method valuation engine. Spec: [SPEC.md](../SPEC.md). Model card: [model_card.md](model_card.md).

**Engineering pass ≠ investment alpha.** Synthetic runs always label `INVESTMENT_VALUE_NOT_ESTABLISHED`.

## End-to-end flow

```
CSV/Parquet (+ SYNTHETIC) / optional HiThink NOTICE
  → load_directory → LoadResult
  → PIT snapshot + data-quality gates
  → economic profile classifier (multi-label + confidence)
  → method registry + hard-gate router (no silent default DCF)
  → driver / regime / path simulation (fundamental track)
  → method-specific distributions (cash-flow / multiples / RIM / NAV / SOTP)
  → method comparison (disagreement preserved; ensemble only if calibrated)
  → independent market-pricing state → exit-price paths (Track B)
  → entry-price-conditioned return distributions
  → diagnostics / sensitivity / walk-forward evaluation
  → versioned result bundle (+ optional DSDE consumer view)
```

Facade: `ValuationEngine` (SPEC §18.1). CLI: `vms` (phase0…phase12, validate-bundle, evaluate, …).

## Module map

| Area | Package | Notes |
|---|---|---|
| Contracts / config | `vms.schemas` | Typed; versioned |
| PIT + quality | `vms.pit`, `vms.quality` | `as_of` integrity |
| Profiles | `vms.profiles` | Rule-based classifier |
| Drivers / regimes / sampling | `vms.drivers`, `vms.regimes`, `vms.sampling` | HMM deferred |
| Statements / capital alloc | `vms.statements`, `vms.capital_allocation` | Accounting invariants |
| Methods | `vms.methods.*` | Plugin registry |
| Router / ensemble | `vms.router`, `vms.ensemble` | Compatibility before blend |
| Market pricing / returns | `vms.market_pricing`, `vms.returns` | Intrinsic ≠ exit by default |
| Evaluation | `vms.evaluation` | Chronological only |
| Reporting | `vms.reporting` | Phase bundles + §16.3 validation |
| DSDE adapter | `vms.adapters.dsde` | Optional; core never imports DSDE |

## Result bundle (§16.3)

Full aspirational tree is listed in SPEC §16.3. Phase CLIs emit **documented subsets** —
see `vms.reporting.bundle_validation.PHASE_CLI_SUBSETS` and `vms validate-bundle`.

Phase 12 mature offline example aims at: profile + eligibility + method_results +
market_pricing_report + exit_price_summary + return_distribution_summary + diagnostics +
validation_report.

## Offline examples (Phase 12)

| Pattern | Directory | Behavior |
|---|---|---|
| Mature operating | `examples/synthetic_mature_operating/` | Full Track A + Track B smoke |
| Growth / neg-FCF | `examples/synthetic_growth_company/` | Routing + multiples attempt / diagnosis |
| Bank | `examples/synthetic_bank/` | RIM; industrial FCFF disabled |
| Cyclical | `examples/synthetic_cyclical/` | HIGH_CYCLICALITY routing diagnosis |
| Holding | `examples/synthetic_holding_company/` | SOTP/NAV or data-gap |

```bash
vms phase12 --out /tmp/vms_phase12 --paths 20
scripts/run_offline_examples.sh /tmp/vms_offline
```

## Component status (Phases 0–12)

Phases 0–11 deliver contracts through walk-forward calibration. Phase 12 packages docs,
examples, bundle validation, schema/config migration tests, and release notes (`0.2.0rc1`).
`ENSEMBLE_CALIBRATED` / `INVESTMENT_VALUE_SUPPORTED` are **not** claimed.
