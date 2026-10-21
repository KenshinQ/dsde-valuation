# Phase 9 — Market-pricing regime and exit-price engine: DONE (VMS-0.2 §20 / §24)

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior freeze tag: `vms-0.1`. Spec: `SPEC.md` (VMS-0.2). Prior: [PHASE8_DONE.md](PHASE8_DONE.md).

Status: **all Phase 9 acceptance criteria pass** for independent market-state estimation,
conditional terminal-multiple exit prices, persistence baseline when MR is unsupported,
lineage preservation, and persistence vs mean-reversion sensitivity. Label:
`ENGINEERING_PASS` for Phase 9 only; `INVESTMENT_VALUE_NOT_ESTABLISHED`.
This is **not** investment advice and does **not** claim investment value.
**No** `INVESTMENT_VALUE_SUPPORTED`. Phases 10+ (return-grid polish / walk-forward) are **not** claimed done.

> Note: an older VMS-0.1 `PHASE9_DONE.md` (walk-forward evaluation under 0.1 numbering) is
> superseded by this VMS-0.2 Phase 9 report. The 0.1 evaluation work remains in `vms.evaluation`
> / CLI `vms evaluate` and is covered by retained evaluation suites. Under VMS-0.2 numbering,
> walk-forward calibration is Phase 11.

## Changed / added files (VMS-0.2 Phase 9)
```
src/vms/__init__.py                         SCHEMA_VERSION=vms-0.2.phase9, PHASE_9
src/vms/assumptions.py                      MARKET-PRICING-* / EXIT-PRICE-* / CONVERGENCE-* IDs
src/vms/market_pricing/schemas.py           estimator_phase=PHASE_9; fallback prior helper
src/vms/market_pricing/config.py            NEW: MarketPricingConfig (+ families, MR, convergence)
src/vms/market_pricing/estimator.py         NEW: independent z-score / fallback estimator
src/vms/market_pricing/transitions.py       NEW: persistence baseline + configured slow/fast MR
src/vms/market_pricing/terminal_multiples.py NEW: state-conditional terminal multiple draws
src/vms/market_pricing/path_metrics.py      NEW: horizon metric extraction from financial paths
src/vms/market_pricing/exit_prices.py       NEW: ExitPriceBundle / generate_exit_prices (§14.4)
src/vms/market_pricing/convergence.py       NEW: explicit CONVERGENCE_TO_INTRINSIC only
src/vms/market_pricing/sensitivity.py       NEW: persistence vs MR sensitivity report
src/vms/market_pricing/__init__.py          lazy exports (avoid config circular import)
src/vms/schemas/config.py                   market_pricing: MarketPricingConfig on VMSConfig
src/vms/reporting/phase9_bundle.py          NEW: offline emitter
src/vms/cli/main.py                         `vms phase9`
config/default.yaml (+ sidecars)            versions → phase9; market_pricing block
tests/unit/test_phase9_acceptance.py        NEW (§20 AC1–AC5)
tests/property/test_exit_price_properties.py NEW (§21.2 no silent intrinsic→exit)
tests/integration/test_cli_phase9.py        NEW
PHASE9_DONE.md / README.md / docs/assumptions.md
```

## Commands executed
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` (Python 3.13) | `python -m pytest` | **630 passed** (Phase 8 was **615**; +15) |
| CLI | `vms phase9 --out /tmp/vms_phase9_smoke --seed 42 --paths 20 --years 3 --horizons 1,3` | `PHASE9_MARKET_PRICING_EXIT_NOT_INVESTMENT_ADVICE`; default_silent_intrinsic_copy_detected=false; persistence baseline; MR=UNSUPPORTED |

## Acceptance criterion → evidence (§20 Phase 9 / §24)

| # | Criterion (SPEC §20 Phase 9) | Evidence |
|---|---|---|
| 1 | Fundamental and market pricing states evolve independently unless an explicitly estimated dependence is configured | Estimator takes only market multiples (no fundamental regimes). `dependence_on_fundamentals="NONE"` by default; `apply_configured_dependence` is opt-in. Vocabularies disjoint. `test_ac1_*` |
| 2 | Constant-state / current-state persistence baseline runs even when mean-reversion estimation is unsupported | `constant_state_persistence()` always available; `mean_reversion.estimation_status=UNSUPPORTED` still yields valid exit bundle via `compare_persistence_vs_mean_reversion`. `test_ac2_*` |
| 3 | Current intrinsic value is not silently copied to future market price | Default `scenario_kind=TERMINAL_MULTIPLE_DEFAULT` ignores intrinsic map (`intrinsic_value_used=False`, reason `NO_SILENT_INTRINSIC_COPY`). Convergence only via explicit `CONVERGENCE_TO_INTRINSIC`. `test_ac3_*`; property `test_property_fundamental_value_cannot_silently_become_exit` |
| 4 | Exit-price paths preserve metric/multiple/bridge/share-count lineage | `ExitPricePath.lineage` + fields for metric_id, terminal_multiple, denominator, bridge, diluted_shares; CLI `exit_price_path_lineage.json`. `test_ac4_*` |
| 5 | Persistence versus mean-reversion sensitivity is reported | `PersistenceSensitivityReport` with baseline + slow/fast MR and `delta_median_vs_baseline`. `test_ac5_*`; CLI `market_pricing_report.json` |

## Example artifact summary
```text
vms phase9 --out /tmp/vms_phase9_smoke --seed 42 --paths 20 --horizons 1,3
→ status=PHASE9_MARKET_PRICING_EXIT_NOT_INVESTMENT_ADVICE
→ schema_version=vms-0.2.phase9  implemented_phase=PHASE_9
→ default_forbids_intrinsic_copy=true
→ fundamental_regimes_used_for_estimation=false
→ persistence_baseline_model=CONSTANT_STATE_PERSISTENCE
→ mean_reversion_estimation_status=UNSUPPORTED
→ investment_value=INVESTMENT_VALUE_NOT_ESTABLISHED
→ artifacts: market_pricing_report.json, exit_price_summary.json, exit_price_path_lineage.json
```

## Known gaps (honest)
- Return-distribution grid polish / DSDE-facing return contract is **Phase 10** (exit prices only smoked here).
- Walk-forward calibration of market-pricing transitions / terminal multiples is **Phase 11**; MR rates are configured placeholders (`UNSUPPORTED` estimation), not fit from short series.
- Z-score market-state classifier is an explicit labeled heuristic — **not calibrated**.
- Convergence scenario is demo-only; disabled by default in config.
- Synthetic offline paths; no claim that exit-price distributions are investment-relevant.
- Legacy 0.1 `vms returns` / `vms evaluate` remain importable but are not the VMS-0.2 adaptive Track B+return path.
